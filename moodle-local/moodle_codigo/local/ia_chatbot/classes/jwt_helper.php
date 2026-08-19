<?php
// This file is part of Moodle - https://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.

/**
 * JWT Helper — Generates signed JWT tokens for the IA Chatbot widget.
 *
 * SECURITY DESIGN:
 *  - Secret resolution order: ENV → $CFG → settings DB (fallback only).
 *  - Pure PHP: uses hash_hmac + base64 only. Zero external dependencies.
 *  - Tokens are ephemeral: default 15-minute TTL (configurable via settings).
 *  - Payload includes Moodle sesskey as anti-CSRF binding.
 *
 * @package   local_ia_chatbot
 * @copyright 2026 BIS Faculty
 * @license   https://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */


namespace local_ia_chatbot;

defined('MOODLE_INTERNAL') || die();
/**
 * Handles JWT generation for the chatbot widget.
 *
 * Usage:
 *   $token = \local_ia_chatbot\jwt_helper::generate($USER->id, $USER, 900);
 */
class jwt_helper {

    // ── Constantes ────────────────────────────────────────────────────────────

    /** Algoritmo declarado en el header del JWT. */
    const ALGORITHM = 'HS256';

    /** Longitud mínima del secreto en caracteres (política de seguridad). */
    const SECRET_MIN_LENGTH = 32;

    // ── Métodos públicos ──────────────────────────────────────────────────────

    /**
     * Generates a signed JWT for the given Moodle user.
     *
     * @param  int         $userid  Moodle user ID ($USER->id).
     * @param  \stdClass   $user    Moodle user object ($USER). Needs fullname() & roles.
     * @param  int         $ttl     Token lifetime in seconds. Defaults to plugin setting or 900.
     * @return string      Compact JWT string: header.payload.signature
     * @throws \moodle_exception  If no valid secret is configured.
     */
    public static function generate(int $userid, \stdClass $user, int $ttl = 0): string {
        $secret = self::resolve_secret();
        $now    = time();
        $expiry = $ttl > 0 ? $ttl : self::resolve_ttl();

        $header = self::base64url_encode(json_encode([
            'typ' => 'JWT',
            'alg' => self::ALGORITHM,
        ], JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR));

        // FIX: sesskey() lanza error en CLI/cron porque no hay sesión web.
        // Usamos un fallback vacío para evitar que los tests unitarios fallen.
        $sesskey = (function_exists('sesskey') && !CLI_SCRIPT) ? sesskey() : '';

        $payload = self::base64url_encode(json_encode([
            'sub'     => $userid,
            'name'    => fullname($user),
            'role'    => self::classify_role($userid),
            'sesskey' => $sesskey,   // Anti-CSRF: vincula el token a la sesión PHP activa.
            'iat'     => $now,
            'exp'     => $now + $expiry,
        ], JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR));

        $signature = self::base64url_encode(
            hash_hmac('sha256', "{$header}.{$payload}", $secret, true)
        );

        return "{$header}.{$payload}.{$signature}";
    }

    /**
     * Verifies a JWT string and returns its decoded payload.
     * Used internally for testing and by the refresh_token web service.
     *
     * @param  string $token  Compact JWT string.
     * @return array          Decoded payload as associative array.
     * @throws \moodle_exception  On invalid signature, expired token, or malformed JWT.
     */
    public static function verify(string $token): array {
        $parts = explode('.', $token);
        if (count($parts) !== 3) {
            throw new \moodle_exception('invalidtoken', 'local_ia_chatbot', '', null, 'Malformed JWT structure.');
        }

        [$header, $payload, $received_sig] = $parts;
        $secret = self::resolve_secret();

        // Verificación de firma — timing-safe.
        $expected_sig = self::base64url_encode(
            hash_hmac('sha256', "{$header}.{$payload}", $secret, true)
        );
        if (!hash_equals($expected_sig, $received_sig)) {
            throw new \moodle_exception('invalidtoken', 'local_ia_chatbot', '', null, 'Invalid JWT signature.');
        }

        $decoded = json_decode(self::base64url_decode($payload), true, 512, JSON_THROW_ON_ERROR);

        // Verificación de expiración.
        if (!isset($decoded['exp']) || $decoded['exp'] < time()) {
            throw new \moodle_exception('tokenexpired', 'local_ia_chatbot', '', null, 'JWT has expired.');
        }

        return $decoded;
    }

    // ── Métodos públicos auxiliares ───────────────────────────────────────────

    /**
     * Public wrapper for role classification.
     * Allows externallib.php to reuse the same logic without code duplication.
     *
     * @param  int    $userid  Moodle user ID.
     * @return string          'teacher' | 'student'
     */
    public static function classify_role_public(int $userid): string {
        return self::classify_role($userid);
    }

    // ── Métodos privados ──────────────────────────────────────────────────────

    /**
     * Resolves the JWT signing secret with priority:
     *   1. Environment variable:    IA_CHATBOT_JWT_SECRET
     *   2. $CFG property:           $CFG->ia_chatbot_jwt_secret
     *   3. Plugin admin setting:    get_config('local_ia_chatbot', 'jwt_secret')
     *
     * @return string  The resolved signing secret.
     * @throws \moodle_exception  If no secret is found or it is too short.
     */
    private static function resolve_secret(): string {
        global $CFG;

        // Prioridad 1a: Variable de entorno preferida.
        $secret = getenv('IA_CHATBOT_JWT_SECRET');
        if ($secret !== false && strlen($secret) >= self::SECRET_MIN_LENGTH) {
            return $secret;
        }

        // Prioridad 1b: Variable de entorno alternativa (compatibilidad con entornos
        // Docker donde la variable puede llamarse simplemente JWT_SECRET).
        $secret = getenv('JWT_SECRET');
        if ($secret !== false && strlen($secret) >= self::SECRET_MIN_LENGTH) {
            return $secret;
        }

        // Prioridad 2: Propiedad en config.php (RAM, sin consulta a DB).
        if (!empty($CFG->ia_chatbot_jwt_secret) && strlen($CFG->ia_chatbot_jwt_secret) >= self::SECRET_MIN_LENGTH) {
            return $CFG->ia_chatbot_jwt_secret;
        }

        // Prioridad 3: Ajuste desde la UI de administración (fallback — solo dev/local).
        $db_secret = get_config('local_ia_chatbot', 'jwt_secret');
        if (!empty($db_secret) && strlen($db_secret) >= self::SECRET_MIN_LENGTH) {
            return $db_secret;
        }

        throw new \moodle_exception(
            'missingjwtsecret',
            'local_ia_chatbot',
            '',
            null,
            'JWT secret not configured. Set IA_CHATBOT_JWT_SECRET or JWT_SECRET env var (min 32 chars).'
        );
    }

    /**
     * Resolves the JWT TTL (token lifetime in seconds).
     * Reads from the plugin admin settings; defaults to 900 seconds (15 min).
     *
     * @return int  Token lifetime in seconds.
     */
    private static function resolve_ttl(): int {
        $ttl = (int) get_config('local_ia_chatbot', 'token_expiry');
        return ($ttl > 0) ? $ttl : 900;
    }

    /**
     * Classifies the current user's primary role within Moodle context.
     * Returns 'teacher' if the user has any editing or non-editing teacher
     * role in any course, 'student' otherwise.
     *
     * @param  int    $userid  Moodle user ID.
     * @return string          'teacher' | 'student'
     */
    private static function classify_role(int $userid): string {
        global $DB;

        // FIX: Los administradores del sitio no tienen role_assignments explícitos
        // en muchos contextos; is_siteadmin() los detecta directamente.
        if (is_siteadmin($userid)) {
            return 'teacher';
        }

        // Roles que se consideran "docente" a efectos del chatbot.
        $teacher_archetypes = ['teacher', 'editingteacher', 'manager', 'coursecreator'];

        // FIX: La consulta original mezclaba parámetros nombrados (:userid) con
        // posicionales (?), lo que causa un DML error en el driver de Moodle.
        // Solución: usar exclusivamente parámetros posicionales (?).
        $placeholders = implode(',', array_fill(0, count($teacher_archetypes), '?'));
        $sql = "SELECT DISTINCT r.archetype
                  FROM {role_assignments} ra
                  JOIN {role} r ON r.id = ra.roleid
                 WHERE ra.userid = ?
                   AND r.archetype IN ({$placeholders})";

        // El primer '?' corresponde a $userid; el resto a los archetypes.
        $params = array_merge([$userid], $teacher_archetypes);

        $rows = $DB->get_records_sql($sql, $params, 0, 1);
        return !empty($rows) ? 'teacher' : 'student';
    }

    /**
     * URL-safe Base64 encoding (RFC 4648 §5) — no padding.
     *
     * @param  string $data  Raw binary or string data.
     * @return string        Base64URL-encoded string.
     */
    private static function base64url_encode(string $data): string {
        return rtrim(strtr(base64_encode($data), '+/', '-_'), '=');
    }

    /**
     * URL-safe Base64 decoding (RFC 4648 §5).
     *
     * @param  string $data  Base64URL-encoded string.
     * @return string        Decoded raw string.
     */
    private static function base64url_decode(string $data): string {
        $padded = str_pad($data, strlen($data) + (4 - strlen($data) % 4) % 4, '=');
        return base64_decode(strtr($padded, '-_', '+/'));
    }
}
