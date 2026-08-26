# Configuración de Permisos en Moodle para el Chatbot Académico

Para que el Chatbot pueda leer los cursos, tareas, notas y agendar eventos, el usuario de **Web Services** asociado al token (`moodle_ws_token` y `moodle_ws_token_write`) debe tener asignados ciertos permisos (capabilities) en Moodle.

## Pasos para Configurar el Rol

1. **Crear un Rol Personalizado (o editar uno existente)**:
   - Ve a **Administración del sitio** > **Usuarios** > **Permisos** > **Definir roles**.
   - Crea un nuevo rol llamado `Chatbot WebService`.
   - Contextos en los que se puede asignar este rol: **Sistema**.

2. **Asignar Capabilities (Permisos)**:
   Asegúrate de marcar como "Permitido" las siguientes capabilities:
   
   - **Lectura General:**
     - `moodle/webservice:createtoken`
     - `webservice/rest:use`
     - `core_enrol_get_users_courses` (Ver cursos inscriptos).
     - `core_course_get_contents` (Ver archivos del curso).

   - **Tareas y Notas:**
     - `mod/assign:view` (Para listar tareas).
     - `moodle/grade:viewall` o `gradereport/user:view` (Para consultar notas).
     - `mod_assign_get_assignments`
     - `gradereport_user_get_grade_items`

   - **Calendario (Escritura y Lectura Avanzada):**
     - `moodle/calendar:manageownentries` (Crucial para que el bot pueda crear eventos de tipo 'user' a nombre del estudiante autenticado).
     - `core_calendar_create_calendar_events`
     - `core_calendar_get_action_events_by_timesort` (Para leer las tareas pendientes del calendario).

3. **Asignar el Rol al Usuario de Web Services**:
   - Ve a **Administración del sitio** > **Usuarios** > **Permisos** > **Asignar roles globales**.
   - Asigna el rol `Chatbot WebService` al usuario que el chatbot utiliza para autenticarse contra la API REST de Moodle.

4. **Verificar el Servicio Web**:
   - Ve a **Administración del sitio** > **Servicios Web** > **Servicios Externos**.
   - Selecciona el servicio utilizado por el chatbot y asegúrate de que las funciones mencionadas estén agregadas a la lista de funciones del servicio.
