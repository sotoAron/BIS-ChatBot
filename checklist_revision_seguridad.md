# Checklist de Revisión: Seguridad, Privacidad y Normativa
## Para uso en la revisión del Informe Técnico del Asistente IA en Moodle

Instrucciones para el agente: para cada ítem, verificar si el documento lo cubre explícitamente, de forma parcial, o no lo cubre. No completar la información faltante — solo señalar el hueco.

---

## 1. Flujo y tratamiento de datos

- [ ] Se especifica exactamente qué campos/datos viajan desde Moodle hacia el backend de IA (no solo el mecanismo de autenticación, sino el payload real: user_id, curso, texto de la pregunta, etc.).
- [ ] Se especifica qué LLM(s) procesa las consultas en **cada** escenario de despliegue descrito (piloto y definitivo), incluyendo si alguno de ellos usa un modelo de terceros/público.
- [ ] Si se usa un modelo de terceros en algún escenario, se explicita qué datos le llegan a ese proveedor y bajo qué política de retención/uso.
- [ ] Se especifica si el backend registra (logging) las preguntas y respuestas de los usuarios, por cuánto tiempo se retienen esos logs, y si están cifrados en reposo.
- [ ] Se especifica dónde y cómo se almacena el historial de conversación más allá del `sessionStorage` del navegador (si existe persistencia del lado del servidor).
- [ ] Se aclara si los datos académicos indexados (planificaciones, boletines) contienen o podrían contener datos personales de terceros (ej. nombres de docentes, direcciones de correo) y cómo se tratan.

## 2. Gestión de secretos y credenciales

- [ ] Se especifica cómo se almacena el `JWT_SECRET` (¿texto plano en `mdl_config_plugins`? ¿cifrado? ¿variable de entorno del backend?).
- [ ] Se especifica un procedimiento de rotación del `JWT_SECRET` en caso de compromiso.
- [ ] Se especifica el mecanismo de resguardo/backup de credenciales de servicio (token de Moodle para ingesta documental).
- [ ] Se aclara la caducidad y el mecanismo de renovación de los tokens JWT de sesión de usuario (más allá de mencionar "1h de validez").

## 3. Superficie de ataque y controles técnicos

- [ ] Se menciona si existe rate limiting / protección contra abuso en el endpoint del backend expuesto a Internet (relevante especialmente en el Escenario A).
- [ ] Se menciona si el backend valida y sanitiza la entrada del usuario antes de pasarla al LLM (protección básica contra inyección de prompt).
- [ ] Se especifica si hubo o está planificado algún análisis de seguridad externo (SAST, revisión de dependencias, pentesting) antes del paso a producción.
- [ ] Se aclara el comportamiento del sistema ante fallos parciales (ej. RAG disponible pero LLM caído, o viceversa), no solo el caso de caída total del backend.
- [ ] Se especifica si las comunicaciones entre Backend y RAG (ChromaDB) están dentro de una red aislada/privada o expuestas de alguna forma.

## 4. Marco normativo y cumplimiento

- [ ] Se hace referencia explícita a la Ley 25.326 de Protección de Datos Personales (Argentina) y cómo el sistema cumple con sus principios (finalidad, consentimiento, proporcionalidad).
- [ ] Se aclara si corresponde algún registro ante la Agencia de Acceso a la Información Pública (AAIP) por el tratamiento de datos de estudiantes.
- [ ] Se menciona si existe una Política de Privacidad o Términos de Uso específicos del asistente, comunicados al estudiante antes de su uso.
- [ ] Se aclara la base de legitimación para el tratamiento de datos académicos de los estudiantes (¿consentimiento? ¿interés legítimo institucional? ¿normativa universitaria existente?).
- [ ] Si aplica normativa institucional propia de la UTN o de la Facultad Regional (reglamentos de uso de TI, resoluciones de Consejo Directivo sobre tratamiento de datos), se hace referencia a ella.

## 5. Gobernanza y responsabilidad operativa

- [ ] Se identifica un responsable técnico/funcional del sistema una vez en producción (no solo "Equipo de Desarrollo e Integración" genérico).
- [ ] Se describe un procedimiento de respuesta ante incidentes (¿qué se hace si se detecta una fuga de datos, un JWT comprometido, o un comportamiento indebido del asistente?).
- [ ] Se aclara la frecuencia y responsable de actualización de la base documental indexada (quién sube nuevas planificaciones/boletines, con qué controles de calidad).
- [ ] Se menciona un canal de contacto o soporte para que Campus/TI pueda reportar problemas o solicitar cambios de configuración.

## 6. Limitaciones y riesgos residuales

- [ ] El documento incluye una sección explícita de riesgos conocidos, limitaciones técnicas o aspectos aún no resueltos (no solo garantías).
- [ ] Se reconoce la posibilidad de que el modelo de lenguaje reformule información de forma imprecisa aunque la fuente indexada sea correcta (limitación inherente a sistemas RAG, no eliminable del todo).
- [ ] Se aclara qué pasa si la documentación indexada está desactualizada o es contradictoria entre fuentes (ej. Boletín vs. Planificación de cátedra) — a qué fuente se le da prioridad.
- [ ] Se identifican explícitamente qué decisiones quedan pendientes de definición (ej. elección final de LLM, infraestructura del Escenario B) en vez de darlas por resueltas implícitamente.

## 7. Consistencia y tono documental

- [ ] No hay afirmaciones absolutas de seguridad ("elimina", "garantiza", "100% seguro", "cero riesgo") que no estén matizadas o sostenidas por el resto del documento.
- [ ] Las garantías declaradas en una sección no son contradichas por el contenido de otra sección (ej. escenarios de despliegue, diagramas de flujo de datos).
- [ ] El documento no contiene rutas de archivos locales, datos de entorno de desarrollo, u otra información que no debería exponerse a un destinatario institucional externo al equipo de desarrollo.

## 8. Estructura del documento

- [ ] Incluye control de versión (versión del documento, fecha, autor/responsable, destinatarios, estado: borrador/final).
- [ ] El resumen ejecutivo comunica qué se solicita al destinatario y cuál es la recomendación del equipo, no solo una lista de funcionalidades.
- [ ] Cierra con próximos pasos concretos (qué acción se espera de Campus/TI: aprobación, revisión, autorización de piloto, etc.).
- [ ] Los diagramas (Mermaid u otros) están en un formato compatible con el canal de entrega confirmado (Markdown renderizado, PDF exportado, Word con imágenes embebidas).
