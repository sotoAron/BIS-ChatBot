El chatbot presenta serios problemas de alusinacion y perdida de contexto. A continuacion te voy a presentar las problematicas para que lleves un analisis de las causas, las soluciones tienen que ser generales y no especificas a las preguntas que generaron el sintoma.

PROBLEMAS DETECTADOS

en referencia al golden dataset las preguntas:

3/14 : ¿Cuáles son las condiciones para promocionar?
Responde correctamente pero se le pasan demasiados chunks. (Pregunta a parte, esto no hace que sea mas lento? no ibamos a elegir los 3 mejores nada mas?)

5/14> quiero saber la fecha del primer parcial

      🤖 Respuesta: "No hay información específica sobre la fecha del primer parcial en el contexto proporcionado."

Responde erroneamente, la informacion de fechas de parciales esta presente en todas las planificaciones. La diferencia puede estar en que se le llaman examenes sumativos y formativos. Debe poder detectar estas fechas en la planificacion dada de la materia.

6/14> cuál es mi nota
    🤖 Respuesta: "Lo siento, pero no tengo información sobre tu nota específica. Para obtener esa información, te recomendaría consultar d..."

Respuesta erronea, deberia consultar en primer lugar a que materia se refiere y si la tiene de contexto, tener la capacidad de leer todas las entregas que estan dentro del curso de la materia, y ver que notas se le asigno a los trabajos y listarlos. Si en el caso de que no hubiera nada, ahi informar que no hay notas registradas o que no puede encontrar notas dentro del curso de esa materia. Deberiamos agregar la posibilidad de ver las notas que tiene en cada entrega, trabajo o actividad. 

8/14 > mis tareas pendientes
 🤖 Respuesta: "Para determinar cuáles son tus tareas pendientes, necesitaría información específica sobre las tareas asignadas a tu cur..."

Respuesta del chabtor en el widget en moodle
 🤖 Respuesta:Lo siento, pero como asistente académico, necesitaría más información sobre el contexto específico. ¿En qué institución educativa y qué plan de estudio te encuentras? Además, ¿en qué asignatura o curso te refieres con "tareas pendientes"? Estos detalles ayudarían a proporcionarte una respuesta más precisa.

Respuesta erronea. Debe simplemente poder extraer del calendario moodle las actividades que aparezcan alli y listarlas. Aca tambien esta el problema de perdida de contexto. Hay que ajustar el system prompt para que sepa que es un asistente academico de la Universidad Tecnologica Nacional. El plan de estudios no es relevante ya que deberia poder sacar del perfil del usuario sus datos de carrera y cursos inscripto, de los cuales tampoco es necesario para esta respuesta porque moodle ya pone las actividades pendientes en su calendario.

9/14> 'qué cursos estoy inscripto'
🤖 Respuesta: "Para saber qué cursos estás inscripto, necesitaría información específica sobre el período académico actual o el plan de..."

Respuesta erronea. El chatbot tiene que poder saber con quien esta hablando, basandose en los datos de sesion. Tiene que poder saber el nombre, los cursos en cuales esta inscripto y la carrera. Informacion que es propia del usuario que le esta hablando el chatbot deberia ser capaz de proporcionarla. Por lo tanto, ante esta pregunta, simplemente deberia poder listar los cursos en los cuales esta inscripto el usuario.

11/14> 'quiero sincronizar el pdf nuevo'
      Etiquetas: [moodle, admin] | Esperado: SYNC
      ✅ Intención: SYNC | Caché: BYPASS | Tiempo: 39.88s
      🤖 Respuesta: "No estoy seguro de qué PDF quieres sincronizar."

Respuesta erronea. El usuario no puede subir pdfs, ni ningun archivo, tampoco modificar nada dentro de los cursos. La unica opcion de escritura que hay es la de agregar nuevas actividades al calendario qeu sean propias de el, y poder eliminar simplemente las que el escribio. Aca el chatbot su unica tarea deberia ser obtener la informacion del usuario para agendar. Por ejemplo, si le pide "agendar que el lunes tengo que entregar el pdf nuevo de sistemas distribuidos", el chatbot deberia mandarle un mejsae de confirmacion que la fecha del evento a agendar porque por lunes se puede entder cualquier lunes, y la materia y asi poder agendar eso en el calendario, obteniendo la fecha actual de la terminal para saber que por ejemplo estamos en 2026 y no en 2025 y pudiendo agregar los datos del curso del usuario para agendar esa actividad.

12/14> '¿Cuándo juega la selección?'
      Etiquetas: [out_of_domain, fallback] | Esperado: RAG
      ✅ Intención: RAG | Caché: MISS | Chunks: [0, 16, 23, 2, 6] | Tiempo: 47.02s
      🤖 Respuesta: "Lo siento, pero no tengo información sobre los horarios de partidos de selecciones de fútbol o deportes similares en tu ..."

Respeusta y proceso completamente erroneo. Primero el tener un intender de CHITCHAT es inescalable, el llm deberia ser capaz de identificar rapidamente cuando una pregutna no corresponde al dominio. Y fallo rotundamente porque incluso se buscaron chunks y llamo a la intencion rag, cuando automaticamente deberia haber respondido que es un asistente academico y esa infromacion no la tiene (dicho mas formalmente). Aca hay un error basico de RAG, y es que debe ser capaz de detectar que la informacion no esta en el contexto.

Otros problemas:

En el widget del chatbot, el chat se pierde cada vez que cierro o abro el widget o recargo la pagina, o entro a un curso o salgo de la subapgina en la que estoy. Deberia poder mantener el contexto de la conversacion al menos por unos minutos.

Por lo tanto necesito que arregles todo lo que sea necesario para solucionar estos problemas.