# Prompt para el agente: Rediseño de la estrategia de chunking e indexación

## Contexto

Estamos construyendo un chatbot para una facultad universitaria que responde preguntas sobre las Planificaciones Anuales de las materias. Estos documentos son PDFs con un **template institucional fijo** (mandado por Rectorado UTN), compuesto por 13 secciones numeradas idénticas en estructura para todas las materias de todas las carreras:

1. Datos Descriptivos
2. Estructura de la cátedra
3. Fundamentación
4. Resultados de Aprendizaje previos requeridos
5. Competencias y Capacidades vinculadas
6. Programa Analítico, Unidades Temáticas
7. Propuesta para el desarrollo de los procesos de Enseñanza y Aprendizaje (tabla RA x Unidad x Estrategias x Evaluación)
8. Recomendaciones para el estudio de la Asignatura (incluye subsección "Uso responsable y ético de la IA")
9. Detalle y cronograma de trabajo de campo/pasantías
10. Sistema de Acreditación (con subsecciones 10.1 Aprobación Directa y 10.2 Aprobación de Cursada)
11. Cronograma (tabla semana a semana, 16-18 filas)
12. Bibliografía según Normas APA
13. Anexo (reuniones de cátedra, investigación y extensión)

Actualmente el sistema usa **chunking por cantidad fija de caracteres/tokens**, sin conciencia de esta estructura. Esto está causando: cortes a mitad de tabla, pérdida de contexto (filas sueltas sin saber a qué unidad/semana pertenecen), y mala recuperación cuando el usuario pide una sección completa (ej. el cronograma entero).

Hay **3 carreras**, cada una con varias materias, y algunas materias tienen **múltiples comisiones** con planificaciones parcialmente distintas (comparten Fundamentación, Programa Analítico, Competencias y Bibliografía, pero pueden diferir en Estructura de cátedra y Cronograma).

Además de las Planificaciones, el sistema debe convivir con **otros tipos de documentos que no tienen template fijo**, como los Boletines Informativos de Secretaría Académica. Estos documentos:

- No están asociados a una materia específica, sino que aplican a nivel **facultad** o a un subconjunto de **carreras**.
- No tienen numeración de secciones ni estructura repetible entre ediciones; sus "encabezados" son títulos en negrita con emoji, sin un esquema fijo.
- Suelen mezclar, dentro de un mismo bloque temático, información de **varias materias y carreras distintas** (ej. una sección de "Comisiones Especiales" que en un solo párrafo por ícono describe reglas distintas para Análisis Matemático I, Física I, Física II, Álgebra, etc., cada una válida solo para ciertas carreras).
- Tienen **vigencia temporal explícita** (fechas de inscripción, turnos de examen de un ciclo lectivo puntual) que caduca, a diferencia de la Planificación que es válida durante todo el ciclo lectivo vigente.
- Se publican con baja frecuencia (unos pocos boletines por año), a diferencia de las Planificaciones que son decenas/cientos de documentos (una por materia/comisión).

Esta heterogeneidad implica que **no se puede aplicar el mismo parser de 13 secciones a todo**. Hace falta una capa de clasificación de documento previa al chunking, con estrategias específicas por tipo.

## Objetivo

Reemplazar el chunking por tamaño fijo por una **estrategia de chunking estructural por tipo de documento**, con contextualización de chunks y metadata rica, manteniendo **un único almacén de vectores** (no separar físicamente por sección, por carrera, ni por tipo de documento).

## Tareas a implementar

### 0. Capa de clasificación de documento (`document_type`)

Antes de decidir cómo chunkear un archivo, el pipeline debe determinar a qué tipo de documento pertenece. Implementar esto como un patrón "strategy": cada `document_type` tiene su propio parser + reglas de chunking + reglas de metadata, pero todos vuelcan al mismo esquema común de salida (ver punto 4/9).

- **Asignación primaria:** campo obligatorio al momento de la carga, asignado por quien sube el archivo (`planificacion`, `boletin`, `reglamento`, `resolucion`, `instructivo`, etc.). No depender de detección automática como único mecanismo.
- **Fallback heurístico de validación:** detectar señales en el texto extraído para advertir si el `document_type` declarado no coincide con el contenido (ej. si dice "PLANIFICACIÓN ANUAL" y tiene la numeración 1 a 13, debería declararse `planificacion`; si dice "BOLETÍN" en el encabezado, debería declararse `boletin`). Si hay discrepancia, loggear una advertencia en vez de fallar silenciosamente.
- Este documento describe en detalle las estrategias para `planificacion` (puntos 1-8) y `boletin` (punto 9). Para nuevos tipos de documento que aparezcan (reglamentos, resoluciones, instructivos), replicar el mismo enfoque: identificar si el documento tiene estructura fija (template) o no, y elegir entre parser determinístico o segmentación asistida por LLM según corresponda (ver criterio en el punto 9).

---

## A. Estrategia para Planificaciones Anuales (documentos con template fijo)

### 1. Parser estructural del PDF

- Construir un parser (regex/reglas sobre texto extraído, no LLM) que identifique las 13 secciones numeradas y sus subsecciones (ej. 10.1, 10.2) usando los encabezados como anclas, ya que son consistentes en todas las materias.
- El parser debe ser tolerante a variaciones menores de OCR/espaciado pero debe fallar de forma visible (log/alerta) si no logra detectar las 13 secciones esperadas en un documento — no debe seguir silenciosamente con un fallback de chunking por tamaño.
- Extraer también las tablas de forma estructurada (fila por fila, con sus columnas identificadas por encabezado), no como texto plano corrido.

### 2. Reglas de chunking por tipo de contenido

Implementar chunking diferenciado según el tipo de sección detectada:

| Sección | Regla |
|---|---|
| 1. Datos Descriptivos | 1 chunk (tabla clave-valor completa) |
| 2. Estructura de cátedra | 1 chunk por docente/fila |
| 3. Fundamentación | 1 chunk completo (es corta, máx. 200 palabras por especificación del template) |
| 4. Resultados de Aprendizaje previos | 1 chunk por asignatura correlativa (fila) |
| 5. Competencias y Capacidades | 1 chunk por competencia (fila), agrupando su nivel de aporte y capacidades asociadas |
| 6. Programa Analítico | 1 chunk por Unidad Temática |
| 7. Propuesta de Enseñanza-Aprendizaje | 1 chunk por RA (fila completa con todas sus columnas) |
| 8. Recomendaciones para el estudio | 1 chunk para el bloque general + 1 chunk separado para "Uso responsable y ético de la IA" |
| 9. Trabajo de campo/pasantías | 1 chunk (aunque sea breve, mantenerlo identificable) |
| 10. Sistema de Acreditación | 1 chunk para el texto general + 1 chunk para 10.1 + 1 chunk para 10.2 |
| 11. Cronograma | 1 chunk por semana (fila completa: contenido, actividad, RA, observaciones) |
| 12. Bibliografía | 1 chunk para bibliografía básica + 1 chunk para recursos digitales |
| 13. Anexo | 1 chunk por sub-bloque (reuniones de cátedra, investigación/extensión) |

Regla general: nunca cortar a mitad de una fila de tabla ni a mitad de una oración. Si una sección semántica supera ~500-600 tokens, subdividir respetando límites naturales (viñetas, filas), no por conteo de caracteres.

### 3. Contextualización de cada chunk antes de embeber

Antes de generar el embedding, anteponer al texto del chunk un encabezado de contexto generado de forma determinística (sin LLM) con: facultad, carrera, materia, ciclo lectivo, cuatrimestre, comisión (si aplica), sección y subsección. Ejemplo:

```
Contexto: Planificación Anual – Ingeniería en Sistemas de Información – 
Aspectos Avanzados de Calidad de Software – Ciclo Lectivo 2026 – 2do Cuatrimestre – 
Sección: Cronograma – Semana 9 (05/10 al 08/10)

Contenido: [texto de la fila]
```

Guardar tanto el texto original como el texto contextualizado (el contextualizado es el que se embebe; el original es el que se muestra como cita/fuente al usuario si hace falta).

### 4. Esquema de metadata por chunk

Cada chunk debe persistirse con esta metadata mínima (ajustar nombres a nuestro stack):

```json
{
  "chunk_id": "string",
  "facultad": "string",
  "carrera_id": "string",
  "materia_id": "string",
  "nivel": "int",
  "ciclo_lectivo": "int",
  "cuatrimestre": "string",
  "comision_id": "string | null",
  "seccion": "string",
  "subseccion": "string | null",
  "ra_relacionados": ["string"],
  "texto_original": "string",
  "texto_contextualizado": "string",
  "embedding": "vector"
}
```

### 5. Un único almacén, no colecciones separadas por sección ni por carrera

- Todo va a una sola colección/tabla vectorial. La separación por carrera/materia/sección/comisión se resuelve con **filtros sobre metadata**, no con particionamiento físico.
- Esto debe permitir dos ejes de consulta sobre los mismos datos: "dentro de una materia" (filtrar por `materia_id`) y "entre materias/carreras" (filtrar por `carrera_id` + `seccion`, comparando entre varios `materia_id`).

### 6. Manejo de comisiones

- Si una sección es compartida entre comisiones (Fundamentación, Programa Analítico, Competencias, Bibliografía, RA previos), guardar el chunk **una sola vez** con `comision_id = null`.
- Si una sección varía por comisión (típicamente Estructura de cátedra y Cronograma), guardar un chunk por comisión con su `comision_id` correspondiente.
- Al recuperar, la query debe traer: `WHERE materia_id = X AND (comision_id = <comision_del_usuario> OR comision_id IS NULL)`.
- Detectar en el pipeline de ingesta, sección por sección, si el contenido es idéntico entre comisiones de la misma materia/ciclo lectivo, para decidir automáticamente si va con `comision_id = null` o duplicado por comisión.

### 7. Router de intención antes de la recuperación

Implementar una clasificación liviana (basada en reglas/keywords, o un LLM chico) de la pregunta del usuario en 3 tipos, antes de decidir cómo recuperar:

1. **Dato puntual** (ej. "¿cuándo es el parcial?") → búsqueda semántica filtrada por `materia_id` (y `comision_id` si aplica).
2. **Sección/tabla completa** (ej. "dame el cronograma completo", "la bibliografía") → **no usar similitud vectorial**; hacer una consulta estructurada directa `WHERE materia_id = X AND seccion = 'cronograma' ORDER BY subseccion`, para garantizar que no falten filas.
3. **Pregunta abierta o comparativa entre materias/carreras** (ej. "¿qué materias ven testing automatizado?") → búsqueda semántica sin filtrar por `materia_id`, opcionalmente filtrando por `carrera_id` o `seccion`.

### 8. Validación y testing (Planificaciones)

- Sobre un set de PDFs de prueba (idealmente de las 3 carreras), verificar que el parser detecta las 13 secciones en el 100% de los casos.
- Armar un set de preguntas de prueba (una por cada sección típica: fundamentación, competencias, cronograma completo, condiciones de aprobación, bibliografía, comparación entre materias) y verificar que el chunk recuperado es el correcto y está autocontenido (no requiere de otro chunk para tener sentido).
- Loggear qué chunks se recuperaron para cada query en un modo debug, para poder auditar fallos de recall.

---

## B. Estrategia para Boletines y documentos sin template fijo

Estos documentos (ej. "Boletín Inicio Ciclo Lectivo") no tienen numeración ni estructura repetible entre ediciones, aplican a nivel facultad/carreras (no a una materia puntual), y suelen mezclar en un mismo bloque visual información de varias materias y carreras distintas. Requieren un enfoque distinto al de la Planificación.

### 9. Segmentación por bloques temáticos (no por template numerado)

- Detectar los límites de sección usando heurísticas de formato: título en negrita, corto, frecuentemente acompañado de emoji/ícono al inicio, y/o precedido de una línea horizontal separadora.
- Dado el **bajo volumen** de estos documentos (se publican pocas veces por ciclo lectivo, a diferencia de las decenas/cientos de Planificaciones), se justifica usar un LLM como paso de segmentación asistida cuando las heurísticas de formato no sean suficientemente confiables entre ediciones. No aplicar este criterio a las Planificaciones, donde el volumen exige un parser determinístico por costo y estabilidad.
- Cada bloque temático detectado (ej. "Turnos de Exámenes Finales", "Inscripción a Cursado", "Comisiones Especiales", "Exámenes Libres", "Situaciones Académicas Especiales") es candidato natural a chunk, salvo que aplique la regla del punto 10.

### 10. Sub-chunking por entidad dentro de bloques multi-materia

Cuando un bloque temático agrupa información de **varias materias o carreras con reglas distintas para cada una** (ej. "Comisiones Especiales 2026", donde cada ícono describe una materia con su propio esquema CPC/CR por carrera), no dejar todo el bloque como un chunk único. Sub-dividir por entidad (materia), de forma que cada chunk quede autocontenido y específico:

```
Chunk: "Comisiones Especiales 2026 – Física I"
Contenido: [reglas específicas de Física I: CPC/CR, cuatrimestre, carreras afectadas]
materias_relacionadas: ["fisica_i"]
carreras_relacionadas: ["ISI", "IEM", "IQ"]
```

Esto evita que una pregunta puntual sobre una materia tenga que "competir" en similitud semántica contra un chunk gigante que mezcla 6 materias distintas, diluyendo la relevancia.

Aplicar el mismo criterio a otros bloques con la misma forma (ej. "Exámenes Libres", donde cada materia tiene su propio contacto y material de apoyo).

### 11. Metadata extendida para documentos sin `materia_id` único

El esquema de metadata de Planificación (punto 4/9 según numeración final) asume que todo cuelga de una sola `materia_id`. Los Boletines rompen ese supuesto: aplican a nivel facultad, a un subconjunto de carreras, o tocan tangencialmente varias materias sin pertenecerles. Extender el esquema común con estos campos (nulos/vacíos cuando no aplican):

```json
{
  "chunk_id": "string",
  "document_type": "boletin",
  "alcance": "facultad | carrera | materia",
  "carreras_relacionadas": ["ISI", "IEM", "IQ"],
  "materias_relacionadas": ["fisica_i"],
  "comision_tipo": "CPC | CR | integrada | null",
  "ciclo_lectivo": 2026,
  "fecha_publicacion": "2026-02-01",
  "vigente_hasta": "2026-03-11 | null",
  "seccion": "comisiones_especiales",
  "texto_original": "string",
  "texto_contextualizado": "string",
  "embedding": "vector"
}
```

Notar que `carreras_relacionadas` y `materias_relacionadas` son **arrays**, a diferencia de `carrera_id`/`materia_id` (singulares) usados en Planificación, porque un mismo chunk de Boletín puede aplicar legítimamente a varias carreras o materias a la vez.

### 12. Manejo de vigencia temporal

- Registrar `fecha_publicacion` y, cuando el contenido lo permita inferir (fechas de inscripción, turnos de examen), `vigente_hasta`.
- En el momento de la consulta, si `vigente_hasta` ya pasó respecto a la fecha actual, no descartar el chunk pero sí:
  - Despriorizarlo frente a chunks vigentes si hay conflicto de información.
  - Si igualmente se usa en la respuesta, acompañarlo de una aclaración explícita indicando que corresponde a una publicación pasada y que conviene verificar vigencia en el Canal de Difusión Académica.
- Esto es especialmente relevante en este documento: contiene tanto "Turnos de Exámenes Finales - Ciclo Lectivo 2025" (ya vencido) como "Inscripción a Cursado Ciclo Lectivo 2026" (vigente al momento de publicación) en el mismo PDF.

### 13. Catálogo maestro para normalización de entidades

Las carreras y materias en el Boletín aparecen como siglas o nombres abreviados (`ISI`, `IEM`, `IQ`, "Álgebra (LAR)"), que pueden no coincidir textualmente con los nombres completos usados en la Planificación (`materia_id`, `carrera_id`). Para poder cruzar información entre ambos tipos de documento:

- Mantener una tabla/catálogo maestro de carreras y materias, con id canónico, nombre completo y todas las variantes/siglas conocidas.
- En la ingesta de cualquier documento (Planificación o Boletín), normalizar contra este catálogo antes de persistir `carrera_id`/`materia_id`/`carreras_relacionadas`/`materias_relacionadas`.
- Mantener este catálogo como una tabla separada, editable manualmente, ya que es de bajo volumen y cambia con poca frecuencia (agregar una materia o sigla nueva es un evento raro).

### 14. Router de intención: sumar la dimensión de tipo de documento

Extender el router de intención (ya definido para Planificación) para que también decida en qué tipo de documento buscar, no solo qué estrategia de recuperación usar. Ejemplos de heurísticas:

- Preguntas sobre fechas de examen final, inscripción a cursado, comisiones especiales, exámenes libres → buscar primero en `document_type: boletin`.
- Preguntas sobre contenidos, cronograma interno de cátedra, condiciones de acreditación de una materia puntual → buscar en `document_type: planificacion`.
- Preguntas que combinan ambos alcances (ej. "contame todo sobre Física I este cuatrimestre") → consultar ambos tipos y combinar resultados, usando el catálogo maestro del punto 13 para vincular la `materia_id` de la Planificación con las `materias_relacionadas` del Boletín.

Resolver esto con reglas simples de keywords en una primera etapa; escalar a un clasificador más fino solo si las reglas no dan señal clara.

### 15. Validación y testing (Boletines)

- Verificar que bloques multi-materia (Comisiones Especiales, Exámenes Libres) quedan correctamente sub-divididos por entidad, y que cada sub-chunk es recuperable de forma independiente ante una pregunta específica de esa materia.
- Verificar que preguntas sobre fechas ya vencidas (ej. turnos de examen 2025) no se presenten como información vigente sin la aclaración correspondiente.
- Verificar cruces entre Boletín y Planificación usando el catálogo maestro (ej. pregunta que debe combinar cronograma de cátedra + info de comisiones especiales de la misma materia).

---

## Entregable esperado

- Capa de clasificación de `document_type` (punto 0).
- **Planificaciones:** módulo de parsing estructural, generación de chunks + contextualización, pipeline de ingesta con metadata y lógica de comisiones (puntos 1-7), set de tests (punto 8).
- **Boletines/documentos sin template:** módulo de segmentación por bloques temáticos con sub-chunking por entidad, metadata extendida con alcance/vigencia, catálogo maestro de normalización, extensión del router de intención (puntos 9-14), set de tests (punto 15).
- Todo persistido en el **mismo almacén vectorial único**, con `document_type` como un filtro de metadata más, junto a `carrera_id`/`carreras_relacionadas`, `materia_id`/`materias_relacionadas`, `seccion`, `comision_id`/`comision_tipo`.

No implementar todavía la carga completa de las 3 carreras ni el histórico de boletines: primero validar el pipeline completo con la materia de ejemplo y el boletín de ejemplo que te voy a pasar, y una vez aprobado el resultado, escalarlo al resto.
