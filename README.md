# 📂 InfoHub File Manager

Panel de control web para sincronizar archivos locales con **AnythingLLM / InfoHub** de forma automática. Gestiona workspaces, sube documentos y genera descripciones de imágenes con IA usando Ollama local.

---

## ✨ Características

- **🔄 Sincronización automática**: Sube archivos nuevos y detecta cambios en carpetas locales.
- **📁 Organización por workspaces**: Crea workspaces en AnythingLLM automáticamente según la estructura de tus carpetas.
- **🖼️ Descripciones de imágenes con IA**: Genera descripciones detalladas de imágenes usando modelos de visión de Ollama local (ej. `llava`, `llava-phi3`).
- **🧹 Limpieza inteligente**: Detecta archivos eliminados localmente y sincroniza el estado con InfoHub.
- **🖥️ Interfaz web moderna**: Panel de control construido con Flet, accesible desde el navegador.
- **🔒 Seguridad**: Claves API y configuración sensible gestionadas mediante variables de entorno (`.env`), nunca subidas al repositorio.

---

## 🚀 Requisitos

- Python >= 3.10
- [Ollama](https://ollama.com) instalado y corriendo localmente (solo si usas descripciones de imágenes)
- Una instancia de [AnythingLLM](https://anythingllm.com) (self-hosted o cloud) con API Key

---

## 📦 Instalación

1. Clona el repositorio:

```bash
git clone https://github.com/joseme/infohub-file-manager.git
cd infohub-file-manager
```

2. Crea y activa un entorno virtual:

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows
```

3. Instala las dependencias:

```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuración

La app se configura de dos formas, en este orden de prioridad:

1. **`config.json`** (recomendado): se crea automáticamente en el primer arranque con los valores por defecto, y se edita desde el propio panel web (**⚙️ Configuración**) sin tocar archivos a mano.
2. **Variables de entorno / `.env`** (opcional, para overrides de despliegue): si una variable de entorno está definida, tiene prioridad sobre el valor equivalente de `config.json`. Copia `.env.example` a `.env` solo si necesitas este modo:

```bash
cp .env.example .env
```

> **Nota:** `.env` y `config.json` están incluidos en `.gitignore` — ninguno de los dos se sube al repositorio, porque ambos pueden contener tu API key.

### Variables de entorno disponibles

```ini
# AnythingLLM API Configuration
ANYTHINGLLM_API_KEY=tu-api-key-aqui
ANYTHINGLLM_BASE_URL=https://tu-instancia.anythingllm.com

# Ollama Configuration (para descripciones de imágenes)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=bkudler/llava-phi3

# Image Description Settings
IMAGE_DESCRIPTION_ACTIVATE=true

# Application Settings
APP_PORT=8500
APP_TITLE=InfoHub File Manager

# Watched Folders Configuration
WATCHED_FOLDERS_ROOT=/home/usuario/Documentos/infohub

# Logging
LOG_LEVEL=INFO
LOG_FILE=infohub.log
```

### Obtener tu API Key de AnythingLLM

1. Accede a tu instancia de AnythingLLM.
2. Ve a **Settings → Tools → Developer API**.
3. Pégala en el panel **⚙️ Configuración** de la app (o en `ANYTHINGLLM_API_KEY` si usas `.env`).

---

## 📁 Estructura de carpetas esperada

El programa escanea carpetas cuyo nombre comience con **`Infohub`** o **`AnythingLLM`**. Dentro de cada una, las **subcarpetas** se convierten en workspaces.

```
/home/usuario/Documentos/infohub/
└── Infohub_MisDocumentos/
    ├── Trabajo/
    │   ├── informe.pdf
    │   └── presentacion.pptx
    ├── Personal/
    │   ├── notas.txt
    │   └── foto_playa.jpg
    └── Impuestos_2024/
        └── declaracion.pdf
```

- `Trabajo`, `Personal` e `Impuestos_2024` se crearán como workspaces en AnythingLLM.
- Los archivos colocados directamente en `Infohub_MisDocumentos` (sin subcarpeta) serán **ignorados**.

---

## ▶️ Uso

1. Asegúrate de que tu archivo `.env` esté correctamente configurado.

2. Inicia la aplicación:

```bash
python app.py
```

3. Abre tu navegador en:

```
http://localhost:8500
```

### Operaciones disponibles

| Botón | Acción |
|-------|--------|
| **📤 Carga Completa y Limpieza** | Crea workspaces automáticamente, sube archivos nuevos, elimina los borrados y actualiza embeddings. |
| **🗂️ Ordenar Archivos** | Organiza documentos en los workspaces correspondientes. |
| **🧹 Limpiar Carpetas** | Elimina workspaces vacíos. |
| **🔍 Escanear Archivos** | Previsualiza carpetas y workspaces sin subir nada. |
| **🖼️ Descripciones IA** | Genera descripciones de imágenes con Ollama local. |

---

## 🖼️ Descripciones de Imágenes con IA

Cuando activas `IMAGE_DESCRIPTION_ACTIVATE=true`, el programa:

1. Detecta imágenes (`.jpg`, `.png`, `.gif`, etc.) en tus carpetas.
2. Envía cada imagen a tu instancia local de **Ollama** con un modelo de visión (ej. `bkudler/llava-phi3`).
3. Crea un archivo de texto junto a la imagen (`.image_description.txt`) con la descripción generada.
4. Sube ese texto a InfoHub para que puedas buscar imágenes por contenido.

### Descargar el modelo en Ollama

```bash
ollama pull bkudler/llava-phi3
```

Verifica que Ollama esté corriendo:

```bash
curl http://localhost:11434/api/tags
```

---

## 🛠️ Solución de Problemas

**"Los archivos no aparecen en InfoHub"**
- Verifica que estén dentro de una **subcarpeta** (no en la raíz de `Infohub_*`).
- Comprueba que `ANYTHINGLLM_API_KEY` y `ANYTHINGLLM_BASE_URL` sean correctos.
- Revisa los logs en `infohub.log`.

**"Las descripciones de imágenes fallan"**
- Confirma que Ollama está ejecutándose: `ollama serve` o `ollama list`.
- Verifica que el modelo esté descargado: `ollama pull bkudler/llava-phi3`.
- Revisa que `OLLAMA_BASE_URL` apunte a tu instancia local (`http://localhost:11434`).

---

## 📦 Distribución

Además de correr desde código fuente (`python app.py`), hay dos formas de distribuir la app:

### Ejecutable standalone (PyInstaller)

```bash
./build_linux.sh      # genera dist/infohub-file-manager
build_windows.bat      # genera dist\infohub-file-manager.exe
```

El ejecutable lee `config.json` desde su propio directorio (no desde una carpeta temporal), así que puede moverse junto al binario a cualquier máquina.

### Docker

```bash
docker compose up -d --build
```

Publica el panel en `http://localhost:8500`, montando `config.json`, `infohub.log` y `./data` como volúmenes persistentes. Ver `Dockerfile` / `docker-compose.yml`.

### Despliegue remoto

`deploy/deploy.sh` sincroniza el proyecto a un servidor remoto por `rsync` (excluyendo `venv/`, `config.json` y otros archivos locales) y levanta el contenedor con `docker compose`. Usa `deploy/config.blank.json` como plantilla si el servidor no tiene `config.json` todavía:

```bash
./deploy/deploy.sh
```

---

## 🧱 Tecnologías

- [Python](https://www.python.org/)
- [Flet](https://flet.dev/) — Framework UI multiplataforma
- [Requests](https://requests.readthedocs.io/) — Cliente HTTP
- [python-dotenv](https://saurabh-kumar.com/python-dotenv/) — Gestión de variables de entorno
- [Ollama](https://ollama.com/) — Ejecución local de modelos LLM/VLM
- [AnythingLLM](https://anythingllm.com/) — Plataforma de gestión de documentos con IA

---

## 🔒 Seguridad

- **Nunca subas tu archivo `.env`** al repositorio. Está protegido por `.gitignore`.
- Guarda tus claves API (`ANYTHINGLLM_API_KEY`) de forma segura y rota periódicamente.
- **Las variables de entorno tienen prioridad** sobre `config.json`. Si existe `ANYTHINGLLM_API_KEY` en `.env`, ese valor se usa aunque `config.json` tenga otro distinto.
- Si usas Ollama en red, asegúrate de restringir el acceso al puerto `11434`.

---

## 📄 Licencia

Este proyecto es de uso personal. Puedes adaptarlo y mejorarlo según tus necesidades.

---

## 🤝 Contribuciones

¿Tienes ideas de mejora o encontraste un bug? Siéntete libre de abrir un issue o enviar un pull request.
