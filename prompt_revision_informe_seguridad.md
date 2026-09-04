# Prompt para el agente: Revisión del Informe Técnico y de Seguridad (Asistente IA en Moodle)

## Contexto

Tenemos un informe técnico (`informe_tecnico_campus.md`) dirigido al equipo de Administración de Campus Virtual, Dirección de TI y Responsables de Seguridad Informática (CISO), cuyo objetivo es transparentar la arquitectura, permisos, flujo de datos y medidas de ciberseguridad de un plugin de Moodle (`local_ia_chatbot`) que integra un asistente académico basado en IA (RAG sobre planificaciones y documentación de cátedra).

Este documento va a ser leído por perfiles técnicos y de seguridad que van a evaluar si aprueban la instalación del plugin en el Campus Virtual institucional. Por lo tanto, necesita ser **preciso, consistente, sin afirmaciones absolutas no sostenibles, y completo respecto a lo que un CISO típicamente pide ver** antes de aprobar este tipo de integración.

## Objetivo

Revisar el documento adjunto de forma exhaustiva, en tres niveles: (1) consistencia interna y precisión técnica, (2) completitud respecto a un checklist de seguridad y normativa, (3) forma y estructura como documento institucional. El resultado de la revisión debe ser un **informe de hallazgos accionable**, no una reescritura directa del documento — el objetivo es que el responsable del proyecto pueda decidir qué corregir antes de reescribir.

## Tareas a realizar

### 1. Detección de inconsistencias internas

Leer el documento completo y señalar cualquier afirmación que se contradiga con otra parte del mismo documento. Prestar especial atención a:

- Afirmaciones de seguridad/privacidad hechas en una sección (ej. "no se comparten datos con modelos públicos de terceros") que puedan no sostenerse en otra sección (ej. descripción de un escenario de despliegue con backend externo cuyo LLM no se especifica).
- Datos técnicos repetidos en más de un lugar (versión de componente, roles, nombres de funciones de API) que puedan estar escritos de forma distinta entre secciones.
- Diagramas (Mermaid u otros) que describan un flujo que no coincida exactamente con lo explicado en el texto adyacente.

Para cada inconsistencia encontrada, citar las dos secciones en conflicto y explicar por qué son contradictorias o ambiguas.

### 2. Verificación contra el checklist de seguridad y normativa

Usar la plantilla `checklist_revision_seguridad.md` (adjunta) como criterio de completitud. Para cada ítem del checklist:

- Marcar si el documento lo cubre explícitamente, lo cubre de forma parcial/ambigua, o no lo menciona.
- Si lo cubre, citar la sección y una síntesis de qué dice.
- Si no lo cubre o lo cubre parcialmente, señalarlo como hallazgo pendiente, indicando qué información concreta falta agregar.

No completar ni inventar la información faltante: el objetivo de esta tarea es señalar los huecos, no llenarlos. Si algo requiere una decisión técnica que no está en el documento (ej. qué LLM se usa en el escenario piloto), marcarlo explícitamente como "requiere definición del equipo técnico antes de poder documentarse".

### 3. Revisión de tono y afirmaciones absolutas

Identificar todas las frases que hagan afirmaciones de seguridad en términos absolutos (ej. "elimina", "garantiza", "cero riesgo", "100% seguro") y evaluar si son sostenibles dado el resto del documento. Para cada una:

- Indicar si es una afirmación razonable de mantener, o si debería matizarse (ej. "reduce significativamente" en vez de "elimina").
- Verificar si el documento tiene, en algún lugar, una sección que reconozca limitaciones o riesgos residuales. Si no existe, señalarlo como un hallazgo de completitud (ver también ítem correspondiente en el checklist).

### 4. Revisión estructural y de forma

Evaluar el documento contra estos criterios y señalar desvíos:

- ¿Tiene control de documento (versión, autor/responsable, fecha, destinatarios, estado)?
- ¿El resumen ejecutivo permite a un directivo entender en 30 segundos qué se solicita, qué riesgo se evaluó y cuál es la recomendación del equipo técnico? ¿O es solo una enumeración de funcionalidades?
- ¿Hay alguna referencia a rutas de archivo locales, datos de entorno de desarrollo personal, o información que no debería exponerse a un destinatario externo al equipo de desarrollo?
- ¿El uso de callouts/admoniciones (notas, advertencias, tips) es consistente? ¿Se usa el mismo tipo de callout para el mismo tipo de contenido en todo el documento?
- ¿El documento cierra con próximos pasos claros (qué se le pide al destinatario: aprobar, revisar, autorizar un piloto, etc.)?
- ¿Los diagramas están en un formato que el destinatario va a poder visualizar según el canal de entrega (Markdown renderizado, PDF, Word)? Señalar si esto no está confirmado.

### 5. Salida esperada

Generar un informe de hallazgos con esta estructura:

```
## A. Inconsistencias internas
[lista numerada, cada una con: sección A, sección B, descripción del conflicto]

## B. Checklist de seguridad y normativa
[tabla: ítem | estado (cubierto/parcial/faltante) | sección donde se cubre (si aplica) | qué falta agregar]

## C. Afirmaciones a matizar
[lista: frase original | sección | sugerencia de reformulación | motivo]

## D. Hallazgos de forma y estructura
[lista numerada de desvíos respecto a los criterios del punto 4]

## E. Resumen priorizado
[top 5 hallazgos que deberían resolverse antes de enviar el documento, ordenados por severidad: 
 crítico (contradicción de seguridad, dato falso o riesgoso) > importante (hueco de completitud 
 que el destinatario probablemente pregunte) > menor (forma/estilo)]
```

No reescribir el documento en esta etapa. El objetivo es producir el informe de hallazgos para que el responsable del proyecto decida qué corregir y cómo, antes de pedir una reescritura.

## Documento a revisar

Adjunto: `informe_tecnico_campus.md`

## Checklist de referencia

Adjunto: `checklist_revision_seguridad.md`
