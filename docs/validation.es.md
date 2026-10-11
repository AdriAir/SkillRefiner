<!-- section: overview -->
# Evidencias de validación

Preparación de la versión pública de Skill Refiner 0.1.0 el 2026-10-11. Host: macOS, Python 3.12.14, Codex CLI 0.162.0-alpha.17.2. Las dependencias confiables de prueba se instalaron con permiso explícito en un entorno temporal aislado. Los resultados describen comprobaciones observadas y sus límites, no una certificación. Autor y titular: AdriAir; licencia: MIT.

<!-- section: evidence -->
## Verificación actual

- La migración de identidad/estado se desarrolló con pruebas fallidas antes de implementarla. Las pruebas de paquete público y estado XDG/Windows pasaron tras el cambio. Las regresiones de prefijos de secretos también fallaron contra el detector original y pasaron después de reforzarlo.
- Suite completa con rutas temporales canónicas (TMPDIR=/private/tmp): **102 aprobadas, 8 fallidas, 5 omitidas**. Cobertura medida de refinerlib en el proceso principal: **76 %**. El HEAD original, probado en las mismas condiciones, tuvo **82 aprobadas, las mismas 8 fallidas, 5 omitidas**; no se introdujo ninguna prueba fallida nueva.
- Siete fallos existentes se deben a que macOS carece de la primitiva admitida para publicar copias atómicamente; uno se debe a que macOS normaliza nombres Unicode antes de que pueda observarse una colisión. No se debilitó ninguno de esos comportamientos para aprobar pruebas. Aplicar copias corregidas se admite en Windows y Linux con renameat2; en hosts no compatibles, falla de forma cerrada. Esta ejecución no valida la publicación en las plataformas compatibles.
- Pasaron dieciocho casos focalizados de regresión para detección, payload semántico redactado y bloqueo previo a Docker de formatos sintéticos de GitHub, GitLab, Slack, Stripe, AWS temporal y claves privadas DSA multilínea. Las pruebas DSA comprueban el marcador del cuerpo además de la clave completa, evitando aserciones vacías por escapes JSON. El detector sigue siendo heurístico.
- Pasó el validador del paquete: una skill descubrible, referencias/contratos locales válidos, nueve pares documentales bilingües, manifiesto MIT, autoría AdriAir y copias idénticas de licencia en raíz/paquete. Pasó git diff --check.
- Un verificador independiente registró el marketplace local e instaló skill-refiner en un CODEX_HOME temporal mediante la CLI real de Codex. El helper instalado se ejecutó por ruta absoluta y cargó su perfil empaquetado como inglés/profesional/medio. No se modificó la configuración habitual de Codex.
- Los espejos README y SKILL recibieron revisión independiente de significado, comandos, selección de perfil, controles de aprobación y limitaciones. Los IDs coincidentes por sí solos no demuestran equivalencia semántica.

<!-- section: audit -->
## Auditoría Git y de publicación

Durante la auditoría, el repositorio GitHub era privado y solo anunciaba main, coincidente con el commit raíz local a322038f; no anunciaba etiquetas remotas. El clon local no era superficial. Se revisaron todos los objetos disponibles: **78 objetos (1 commit, 21 árboles, 56 blobs)**, las cuatro refs locales, metadatos/mensajes de commits y tres entradas de reflog. git fsck no encontró errores ni objetos colgantes o inalcanzables. No había almacenes alternativos, refs de reemplazo, grafts, submódulos ni contenido LFS.

No se identificó ninguna credencial real. Las asignaciones con apariencia de credencial, JWT y bloques PEM de los blobs históricos eran fixtures sintéticos o patrones del detector. Los análisis de contenido no encontraron correos privados, rutas personales del host, URLs internas ni archivos de credenciales. Los metadatos de autor/committer del único commit sí contienen un correo personal, y su árbol conserva la identidad anterior y una licencia restrictiva. Esos registros históricos son distintos del árbol de trabajo saneado y todavía requieren sustituir el historial con aprobación explícita para cumplir el requisito estricto de publicación.

Dos refs locales de snapshots de Codex contienen un binario .DS_Store adicional al árbol de la rama. No mostró correos, rutas del host, URLs ni marcadores de secreto. El árbol actual lo ignora y no debe publicarse. Un push ordinario de main no incluye reflogs ni refs locales de snapshots; no uses un push espejo para esta entrega.

Limpieza propuesta del historial: sustituir el único commit raíz por el árbol público revisado, usar la identidad GitHub noreply verificada del propietario y actualizar solo main con una condición explícita sobre el SHA anterior esperado. El commit, la sustitución del historial y el push requieren aprobación humana separada. Mantén privado el repositorio hasta comprobar de nuevo el historial anunciado. Reescribir refs no garantiza borrar otras copias ni cachés de GitHub; consulta la [documentación de eliminación de GitHub](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

<!-- section: limitations -->
## Comprobaciones bloqueadas y no realizadas

El daemon Docker local no estaba arrancado, incluso tras comprobar su acceso con autorización. Los cinco casos optativos produjeron un aprobado y cuatro fallos por motor Linux inaccesible; no validan la ejecución ni el aislamiento de contenedores en esta sesión. No se arrancó ningún daemon ni se descargó ninguna imagen.

No se instaló un escáner externo específico de secretos. La auditoría combinó enumeración de todos los objetos, inspección de patrones/contenido, revisión de metadatos y clasificación manual de coincidencias sintéticas; los secretos desconocidos o codificados pueden escapar a estas comprobaciones. No se garantiza confidencialidad absoluta.

No realizado: pruebas nuevas en hosts Windows/Linux, instalación en la configuración habitual de Codex, QA de escritorio/navegador, ejecución autónoma de agentes objetivo, commit, reescritura del historial, push o cambio de visibilidad del repositorio. Preparar el árbol de trabajo actual no elimina por sí solo nada de commits ya subidos. Los artefactos privados y entradas originales deben permanecer fuera del control de versiones; las copias corregidas tienen vida independiente.
