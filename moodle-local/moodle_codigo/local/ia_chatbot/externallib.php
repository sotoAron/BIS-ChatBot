<?php
// This file is part of Moodle - https://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

/**
 * External functions for local_ia_chatbot.
 *
 * SECURITY CONTRACT: Every function in this class is Read-Only.
 * No INSERT, UPDATE, or DELETE operations are performed on Moodle's database.
 *
 * @package   local_ia_chatbot
 * @copyright 2026 BIS Faculty
 * @license   https://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

require_once($CFG->libdir . '/externallib.php');
require_once($CFG->dirroot . '/local/ia_chatbot/classes/jwt_helper.php');

use local_ia_chatbot\jwt_helper;

/**
 * External API class for the IA Chatbot plugin.
 *
 * Exposes two AJAX-callable functions:
 *   - get_user_context: returns enrolled courses, name, and role.
 *   - refresh_token: issues a fresh JWT for the current session.
 */
class local_ia_chatbot_external extends external_api {

    // ═══════════════════════════════════════════════════════════════════════════
    // get_user_context
    // ═══════════════════════════════════════════════════════════════════════════

    /**
     * Parameter definition for get_user_context.
     *
     * @return external_function_parameters
     */
    public static function get_user_context_parameters(): external_function_parameters {
        return new external_function_parameters([
            // Esta función no requiere parámetros de entrada;
            // opera exclusivamente sobre el $USER autenticado.
        ]);
    }

    /**
     * Returns the current user's academic context.
     * Strictly Read-Only — no writes to Moodle DB.
     *
     * @return array  Associative array with user context data.
     * @throws required_capability_exception  If user lacks local/ia_chatbot:use.
     */
    public static function get_user_context(): array {
        global $USER, $DB;

        // Verificación de capacidad.
        $context = \context_system::instance();
        self::validate_context($context);
        require_capability('local/ia_chatbot:use', $context);

        // Obtener cursos matriculados del usuario (solo activos).
        $enrolled_courses = enrol_get_users_courses($USER->id, true, ['id', 'fullname', 'shortname']);

        $courses = [];
        foreach ($enrolled_courses as $course) {
            $courses[] = [
                'id'        => (int) $course->id,
                'fullname'  => (string) $course->fullname,
                'shortname' => (string) $course->shortname,
            ];
        }

        return [
            'userid'   => (int) $USER->id,
            'fullname' => fullname($USER),
            'role'     => jwt_helper::classify_role_public($USER->id),
            'courses'  => $courses,
            'sesskey'  => sesskey(),
        ];
    }

    /**
     * Return value definition for get_user_context.
     *
     * @return external_single_structure
     */
    public static function get_user_context_returns(): external_single_structure {
        return new external_single_structure([
            'userid'   => new external_value(PARAM_INT,    'Moodle user ID'),
            'fullname' => new external_value(PARAM_TEXT,   'User full name'),
            'role'     => new external_value(PARAM_ALPHA,  'Classified role: student or teacher'),
            'sesskey'  => new external_value(PARAM_ALPHANUM, 'Current Moodle session key (anti-CSRF)'),
            'courses'  => new external_multiple_structure(
                new external_single_structure([
                    'id'        => new external_value(PARAM_INT,  'Course ID'),
                    'fullname'  => new external_value(PARAM_TEXT, 'Course full name'),
                    'shortname' => new external_value(PARAM_TEXT, 'Course short name'),
                ])
            ),
        ]);
    }

    // ═══════════════════════════════════════════════════════════════════════════
    // refresh_token
    // ═══════════════════════════════════════════════════════════════════════════

    /**
     * Parameter definition for refresh_token.
     *
     * @return external_function_parameters
     */
    public static function refresh_token_parameters(): external_function_parameters {
        return new external_function_parameters([
            // Sin parámetros: el token se genera para el $USER de la sesión activa.
        ]);
    }

    /**
     * Issues a fresh JWT for the current authenticated Moodle session.
     * Called by chatbot.js when it receives a 401 from the FastAPI backend.
     *
     * @return array  Array with 'token' (string) and 'exp' (int, Unix timestamp).
     * @throws required_capability_exception  If user lacks local/ia_chatbot:use.
     */
    public static function refresh_token(): array {
        global $USER;

        $context = \context_system::instance();
        self::validate_context($context);
        require_capability('local/ia_chatbot:use', $context);

        $ttl   = (int) get_config('local_ia_chatbot', 'token_expiry') ?: 900;
        $token = jwt_helper::generate($USER->id, $USER, $ttl);

        return [
            'token' => $token,
            'exp'   => time() + $ttl,
        ];
    }

    /**
     * Return value definition for refresh_token.
     *
     * @return external_single_structure
     */
    public static function refresh_token_returns(): external_single_structure {
        return new external_single_structure([
            'token' => new external_value(PARAM_RAW,  'Freshly signed JWT token'),
            'exp'   => new external_value(PARAM_INT,  'Token expiration Unix timestamp'),
        ]);
    }
}
