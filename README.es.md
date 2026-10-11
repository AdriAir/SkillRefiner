<!-- section: overview -->
# Skill Refiner

[English](README.md) · [Repositorio](https://github.com/AdriAir/SkillRefiner) · [Licencia MIT](LICENSE)

Skill de Codex de código abierto creada por AdriAir, versión 0.1.0: skill-refiner. Cualquier persona puede usarla, modificarla y redistribuirla bajo la licencia MIT, también para uso comercial. Revisa carpetas locales completas buscando riesgos de seguridad, bugs y mejoras con beneficio concreto. Python aporta comprobaciones estáticas acotadas, informes, historial y operaciones sobre copias; Codex realiza el análisis semántico en el chat actual.

Cada propuesta exacta exige una aprobación humana separada. La aplicación crea una copia corregida y conserva intacto el original seleccionado. Su uso no depende de ECC, hooks, servidores MCP ni otra API de modelos.

<!-- section: installation -->
## Instalación

El catálogo está en .agents/plugins/marketplace.json; el manifiesto portable, en plugins/skill-refiner/plugin.json, siguiendo la [documentación oficial de empaquetado](https://developers.openai.com/plugins/build/plugins). El paquete instalado incluye la licencia MIT y una traducción española informativa. Requisitos: Codex con soporte para plugins y Python 3.12+. Docker es opcional para comprobaciones dinámicas aisladas. Obtén el revisor confiable y registra su marketplace local:

~~~sh
git clone https://github.com/AdriAir/SkillRefiner.git
cd SkillRefiner
codex plugin marketplace add .
codex plugin add skill-refiner@skill-refiner-marketplace
~~~

Prepara manualmente un entorno Python. En macOS/Linux:

~~~sh
python3 -m venv .venv
.venv/bin/python -m pip install -r plugins/skill-refiner/skills/skill-refiner/scripts/requirements.txt
~~~

En Windows PowerShell:

~~~powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r plugins/skill-refiner/skills/skill-refiner/scripts/requirements.txt
~~~

Son requisitos del revisor, nunca dependencias obtenidas de una entrada. Reinicia o actualiza el cliente si hace falta. Proporciona a Codex la ruta absoluta a este intérprete Python confiable. Tras instalar, resuelve el helper y los requisitos respecto a la carpeta de la skill instalada; no presupongas que este repositorio sea el directorio actual. Hay un único SKILL.md activo en inglés; references/SKILL.es.md es su espejo documental.

<!-- section: use -->
## Uso desde el chat

Invoca $skill-refiner, por ejemplo: «Revisa la carpeta local existente /ruta/a/mi-skill buscando riesgos de seguridad y bugs. Muestra propuestas precisas y espera mi aprobación separada antes de aplicar cada una». En Windows, una ruta explícita puede ser C:\Skills\mi-skill. Se admiten varias carpetas explícitas. Los nombres se resuelven solo en ubicaciones locales conocidas; las coincidencias ambiguas requieren selección. No se admiten ZIP, descargas ni clonaciones remotas.

La skill obtiene un payload redactado y trata las instrucciones, scripts y salidas de la entrada como datos no confiables. Primero guarda los resultados estáticos con semantic_status: pending. Codex examina el contenido seguro e integra hallazgos concretos con semantic. Una reutilización pendiente también necesita este paso; una completada puede reutilizar sus hallazgos semánticos registrados.

Ejemplo de desarrollo: sustituye los marcadores en mayúsculas por tus rutas, usa el MISMO estado durante todo el flujo y nombres de artefactos nuevos fuera de las entradas y del estado. En macOS/Linux, llama a los mismos argumentos con .venv/bin/python y la ruta del helper directamente:

~~~powershell
$refiner = 'plugins/skill-refiner/skills/skill-refiner/scripts/refiner.py'
$refinerPython = '.venv/Scripts/python.exe'
$profile = 'plugins/skill-refiner/skills/skill-refiner/assets/profile.default.json'
& $refinerPython $refiner review TARGET --profile $profile --state-dir STATE --context 'scope and known model version' --report-file REPORT.json
& $refinerPython $refiner payload TARGET
& $refinerPython $refiner semantic TARGET --state-dir STATE --report REPORT.json --findings FINDINGS.json --report-file COMPLETED.json
& $refinerPython $refiner propose TARGET --state-dir STATE --report COMPLETED.json --changes CHANGES.json --purpose 'Concrete benefit' --risk 'Risks' --verification 'Expected check' --proposal-file PROPOSAL.json
# ONLY AFTER SEPARATE HUMAN APPROVAL / SOLO TRAS APROBACION HUMANA SEPARADA
& $refinerPython $refiner approve --target TARGET --report COMPLETED.json --state-dir STATE --proposal-file PROPOSAL.json --base-digest BASE_HASH --proposal-digest PROPOSAL_HASH --decision apply --approval-file APPROVAL.json
& $refinerPython $refiner apply TARGET --state-dir STATE --proposal-file PROPOSAL.json --approval-file APPROVAL.json --output NEW_COPY
~~~

Antes de semantic, Codex escribe un FINDINGS.json temporal con un array de objetos: rule, path (o path_digest para nombres enmascarados), evidence, category, severity y message. El motor deriva IDs, líneas y procedencia. Los hallazgos semánticos siguen sin verificar en el informe; las reproducciones dinámicas controladas son evidencias separadas.

Antes de propose, Codex escribe CHANGES.json. Cada entrada admite {"path":"file","old":"fragmento exacto único","new":"reemplazo"} o {"path":"file","content":"reemplazo UTF-8 completo"}; content: null elimina un archivo. Conserva los valores privados ajenos al cambio mediante reemplazos exactos; nunca escribas máscaras de presentación en los archivos. Muestra el diff exacto redactado, finalidad, riesgos y verificación prevista; evita cambios cosméticos o ajenos a la intención de la skill.

Propose exige un informe completado vigente. La aprobación vincula ambos hashes y debe registrarse en el MISMO historial propio antes de apply. Si cambia la entrada o propuesta, hacen falta una propuesta y aprobación nuevas. Rechaza con --decision reject; se elimina la propuesta cruda. Una aplicación correcta elimina los artefactos privados de propuesta y aprobación. Borra los demás archivos temporales de intercambio tras usarlos; una ejecución interrumpida o fallida puede dejarlos para limpieza manual. Guarda todos los artefactos fuera del original y del historial y no los incluyas en Git. La aplicación devuelve hallazgos estáticos de la copia; informa por separado de comprobaciones aprobadas, fallidas, bloqueadas y no realizadas.

<!-- section: configuration -->
## Configuración e historial

El perfil confiable empaquetado es assets/profile.default.json respecto a la carpeta de la skill instalada: inglés, tono profesional y detalle medio. La skill lo carga explícitamente con --profile. Crea un perfil confiable propio fuera de las entradas de revisión para usar español u otras preferencias admitidas. El helper directo sin --profile conserva su alternativa predeterminada en español. Idiomas: es/en; tonos: professional/friendly/direct; detalle: concise/medium/detailed; conventions: lista de preferencias. Usa --profile PATH con review, o profile --profile PATH para consultarlo. Las preferencias no pueden desactivar controles ni ocultar riesgos relevantes.

El historial predeterminado está en %LOCALAPPDATA%\SkillRefiner en Windows, o $XDG_STATE_HOME/skill-refiner / ~/.local/state/skill-refiner en otros sistemas. Cambia --state-dir por una carpeta dedicada vacía; las comprobaciones de propiedad rechazan registros ajenos. Los hashes, informes redactados y decisiones permanecen hasta que forget --state-dir STATE elimina sus registros propios. Las copias corregidas tienen una vida independiente y forget no las borra. El helper no conserva prompts, respuestas crudas de modelos ni instantáneas originales permanentes.

La reutilización exige coincidencia de contenido, identidad de entrada, código del revisor, esquemas, política, perfil, contexto, Python y dependencias registradas. Incluye los supuestos relevantes del proyecto y el modelo/versión conocido de Codex en --context; el helper no puede descubrir el modelo del chat ni cambios del servidor. Solo se conserva un hash del contexto. --force-refresh inicia una revisión nueva y compara los hallazgos finales con el historial completado compatible. Los descartes aprobados requieren motivo y caducan cuando cambia la evidencia o política; los riesgos de seguridad aceptados siguen visibles.

La reutilización exacta no demuestra corrección y una inferencia nueva de Codex puede variar. Los IDs dependen de regla, archivo y evidencia, no de redacción o números de línea. Reaplicar una transformación aprobada mediante la biblioteca no cambia su copia final exacta existente; otras salidas existentes se rechazan. El comando del chat normalmente limpia los artefactos de aprobación tras una aplicación correcta.

<!-- section: sandbox -->
## Sandbox Docker

Las comprobaciones dinámicas Python/Bash requieren un motor Docker Linux LOCAL accesible y una imagen confiable fijada por digest ya presente. La preparación confiable puede ejecutar explícitamente:

~~~powershell
docker pull python@sha256:f85c5697265c178cc6887276c55fe16cf3d14ca35c3df6a5eab3b360534a55d2
~~~

El helper nunca descarga imágenes ni instala dependencias de las entradas. Usa sandbox TARGET --script scripts/check.py --args ARGUMENT. Valores por prueba: 1 CPU, 512 MiB, 64 procesos, 30 segundos y 1 MiB de salida capturada. Solo ajustes solicitados por el usuario pueden cambiar --cpus, --memory-mib, --pids, --timeout, --output-bytes o la imagen confiable --image.

Los contenedores usan un usuario sin privilegios, red deshabilitada, raíz/entrada de solo lectura, entorno mínimo de la imagen, sin credenciales del host ni socket Docker, y /work y /tmp efímeros. Python se ejecuta con -I; los imports de módulos vecinos y las dependencias ausentes pueden fallar. Los bytes, nombres o argumentos con apariencia de secreto bloquean la ejecución: prepara y aprueba antes una copia de prueba saneada. Si Docker falta o deniega acceso, las comprobaciones dinámicas se bloquean y continúa el análisis estático. Ningún código objetivo se ejecuta en el host.

<!-- section: limitations -->
## Límites

La detección de secretos es heurística; los secretos sin etiqueta o codificados pueden no detectarse. Docker reduce el riesgo de ejecución sin garantizar aislamiento absoluto. La v1 prueba scripts concretos, no una skill objetivo ejecutándose como agente autónomo.

Límites de inventario: 2.000 entradas, profundidad 20 y 100 MiB totales. Los archivos binarios, no UTF-8 y mayores de 5 MiB se incluyen en los hashes y conservan en las copias, pero se omiten del texto semántico. Los metadatos Git se registran como omitidos y se excluyen de las copias. Se rechazan enlaces simbólicos, reparse points, enlaces duros, entradas especiales, escapes y rutas ambiguas. Las copias conservan bytes, no metadatos del sistema de archivos ni carpetas vacías.

Más de 2.000 hallazgos estáticos bloquean explícitamente la generación del informe; divide el alcance en vez de descartar diagnósticos silenciosamente.

Solo se comprueba estáticamente la sintaxis Python; Bash solo se ejecuta en Docker y otros lenguajes reciben análisis de patrones con límites explícitos de sintaxis/ejecución. Los digests de aprobación y marcadores de estado registran integridad del flujo, no identidad humana autenticada. La publicación atómica de copias funciona en Windows y hosts Linux con renameat2; donde no se admite, falla de forma cerrada. La equivalencia de traducciones y utilidad de diagnósticos requieren revisión semántica además de pruebas estructurales. Ni las pruebas ni un payload redactado certifican seguridad. Revisar una skill omite sus metadatos Git y no audita su historial. Antes de publicar una skill revisada, inspecciona por separado su copia final, todos los commits, refs y metadatos de autor. Ignorar un archivo no lo elimina de commits existentes. Las cadenas de este repositorio con apariencia de credencial son pruebas deliberadamente sintéticas; mantén las credenciales reales, perfiles privados, informes y propuestas fuera del control de versiones.

<!-- section: development -->
## Desarrollo y evidencias

Lee AGENTS.md. Instala las dependencias confiables de pruebas pytest==8.4.2 y pytest-cov==7.0.0 en el entorno de desarrollo. Desde la raíz del repositorio, ejecuta python -m pytest y python scripts/validate_package.py con el intérprete de desarrollo (.venv/Scripts/python.exe en Windows o .venv/bin/python en macOS/Linux). Las pruebas Docker son optativas: establece SKILL_REFINER_DOCKER_TESTS=1 antes de pytest tests/test_docker.py; las ejecuciones ordinarias las omiten.

Los permisos Windows pueden exigir ejecutar pruebas de desarrollo CONFIABLES fuera del sandbox restringido del agente; esto nunca autoriza ejecutar entradas en el host. El validador del paquete es exclusivo del repositorio, no un comando del helper instalado. Consulta las [evidencias de validación](docs/validation.es.md), las [fronteras de seguridad](plugins/skill-refiner/skills/skill-refiner/references/security.es.md) y LICENSE. El flujo de revisión de la skill no realiza commits, push ni publicación automáticamente. Este paquete público usa identificadores nuevos de plugin y estado; instálalo como un plugin nuevo. Las instalaciones e historiales locales anteriores no se migran automáticamente. La revisión estática está disponible en macOS; aplicar copias corregidas requiere actualmente Windows o Linux con soporte para renameat2.

<!-- section: license -->
## Licencia

Copyright (c) 2026 AdriAir. Publicado bajo la [licencia MIT](LICENSE). Conserva su aviso de copyright y permisos al redistribuir copias. La [traducción española](LICENSE.es.md) es informativa; la licencia inglesa es la aplicable. El plugin instalado incluye ambos documentos.
