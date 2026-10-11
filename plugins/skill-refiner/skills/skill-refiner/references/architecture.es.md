<!-- section: overview -->
# Arquitectura

El paquete tiene un único `plugin.json` portable, el `SKILL.md` inglés descubrible, su espejo español, `agents/openai.yaml`, el ayudante Python local bajo `scripts/`, esquemas, referencias y pruebas. La raíz del repositorio posee la política de empaquetado y verificación.

<!-- section: interfaces -->
## Interfaces

Los comandos del ayudante son `review`, `payload`, `semantic`, `propose`, `approve`, `apply`, `dismiss`, `forget`, `sandbox` y `profile`. El `scripts/validate_package.py` de la raíz es una herramienta de desarrollo, no un comando del helper instalado. El `pyproject.toml` de la raíz posee las dependencias Python y la configuración de pruebas.
