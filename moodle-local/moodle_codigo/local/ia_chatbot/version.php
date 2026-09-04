<?php
// This file is part of Moodle - https://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// Moodle is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with Moodle.  If not, see <https://www.gnu.org/licenses/>.

/**
 * Plugin version and other meta-data are defined here.
 *
 * @package   local_ia_chatbot
 * @copyright 2026 BIS Faculty
 * @license   https://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

$plugin->component = 'local_ia_chatbot';   // Nombre canónico del plugin.
$plugin->version   = 2026090302;           // YYYYMMDDXX — formato requerido por Moodle.
$plugin->requires  = 2023100900;           // Moodle 4.3 mínimo (build 2023100900).
$plugin->maturity  = MATURITY_ALPHA;       // Alpha: en desarrollo activo.
$plugin->release   = '1.1.2';              // Versión con azul unificado (#0f6cbf) y logo de bordes outline.
