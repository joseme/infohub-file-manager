# 📂 InfoHub File Manager - Guía del Usuario

¡Bienvenido al Administrador de Archivos de InfoHub! Esta herramienta está diseñada para facilitarte la vida sincronizando automáticamente los archivos de tu computadora con tu espacio de trabajo de InfoHub (AnythingLLM). Olvídate de las subidas manuales: solo suelta un archivo en una carpeta y la IA se encarga del resto.

---

## 🌟 ¿Qué hace esta herramienta?
Imagina una "Carpeta Mágica" en tu computadora. Cada vez que pongas un documento o imagen en esa carpeta, este programa:
1. **Detecta** el nuevo archivo.
2. **Crea** un espacio de trabajo (workspace) en InfoHub que coincide con el nombre de tu carpeta.
3. **Sube** el archivo automáticamente.
4. **Describe con IA** tus imágenes para que puedas buscarlas usando palabras (por ejemplo, buscar "atardecer" encontrará una imagen de un atardecer aunque el archivo se llame `IMG_1234.jpg`).

---

## 🚀 Primeros Pasos (Configuración Inicial)

### 1. Configuración de la "Carpeta Mágica"
El programa busca carpetas que empiecen con la palabra **"Infohub"** (con 'b' minúscula) o **"AnythingLLM"**. 

**Ejemplo de cómo organizar tus archivos:**
Crea una carpeta principal llamada `Infohub_MisDocumentos`. Dentro de ella, crea subcarpetas para tus diferentes proyectos:
- `Infohub_MisDocumentos/Trabajo` $\rightarrow$ (Todo aquí irá al espacio de trabajo **Trabajo** en InfoHub)
- `Infohub_MisDocumentos/Personal` $\rightarrow$ (Todo aquí irá al espacio de trabajo **Personal**)
- `Infohub_MisDocumentos/Impuestos_2024` $\rightarrow$ (Todo aquí irá al espacio de trabajo **Impuestos_2024**)

**Subcarpetas dentro de un proyecto:**
También puedes crear subcarpetas dentro de un proyecto y se subirán igualmente, guardando el nombre de la carpeta en el nombre del archivo remoto. Por ejemplo:
- `Infohub_MisDocumentos/Trabajo/Sub/archivo.pdf` $\rightarrow$ se sube a **Trabajo** como `Sub__archivo.pdf`.
- Esto evita colisiones: `Trabajo/A/informe.pdf` y `Trabajo/B/informe.pdf` se suben como `A__informe.pdf` y `B__informe.pdf`, sin pisarse.

> ℹ️ InfoHub no admite carpetas anidadas reales, por eso la carpeta se guarda en el nombre del archivo (separador `__`).
> Los archivos `.image_description` y `.image_description.txt` no se suben: son textos que genera la propia app.

> ⚠️ **Importante**: Los archivos colocados directamente en la carpeta principal `Infohub_MisDocumentos` son ignorados. **Debes** usar subcarpetas para definir tus espacios de trabajo.

### 2. Conexión con InfoHub
Para que la "magia" funcione, el programa necesita dos cosas de la configuración de InfoHub:
1. **Clave API (API Key)**: Se encuentra en *Settings $\rightarrow$ Tools $\rightarrow$ Developer API*.
2. **URL**: La dirección web que usas para acceder a tu instancia de InfoHub.

---

## 🖥️ Uso del Panel de Control Web
No necesitas ser programador para activar las actualizaciones. Puedes usar la interfaz web sencilla.

**Cómo acceder:**
Abre tu navegador y ve a: `http://localhost:8000`

### Recorrido guiado
La primera vez que abres el panel, un recorrido te muestra cada parte en pocos pasos. Puedes cerrarlo cuando quieras y verlo otra vez con el botón **?** de la barra superior. El navegador recuerda que ya lo viste; en otro navegador o en una ventana privada aparece de nuevo.

### ¿Qué hacen los botones?
*   **📤 Full Upload and Cleaning (Subida completa y limpieza)**: Este es el botón de "Hacer todo". Escanea tus carpetas, sube archivos nuevos, actualiza los cambiados y elimina los archivos que hayas borrado de tu computadora.
*   **🗂️ Sort Files (Ordenar archivos)**: Organiza automáticamente tus documentos en las carpetas correctas según su espacio de trabajo.
*   **🧹 Clean Folders (Limpiar carpetas)**: Limpia workspaces vacíos en InfoHub (función en desarrollo).
*   **🔍 Scan Files (Escanear archivos)**: Solo "mira" tus carpetas para ver si algo ha cambiado, sin subir nada.
*   **🖼️ Create Image Descriptions (Crear descripciones de imágenes)**: Genera descripciones con IA para imágenes usando Ollama Cloud.

---

## 🎯 Modo demo (prospectos de InfoHub)
Si te dieron una demo de InfoHub, el File Manager es la forma de cargar tus documentos. Después los consultás en InfoHub Chat.

1. **Iniciá sesión** con la URL de InfoHub, el usuario y la contraseña de tu demo. Están en «Mi demo», dentro de InfoHub Chat. No hace falta API key: el panel detecta la demo y muestra solo lo que necesitás.
2. **Elegí una carpeta** de tu equipo con «Elegir carpeta». Si el selector no se abre, escribí la ruta y presioná Enter. Dentro se crea una subcarpeta por cada workspace de tu demo, por ejemplo «Contratos», «Normativa y jurisprudencia» y «Expedientes».
3. **Copiá tus documentos** en la subcarpeta que corresponda. Dentro de cada una podés armar subcarpetas.
4. **Sincronizá.** Se suben los archivos nuevos y se quitan de InfoHub los que borraste de la carpeta, así recuperás su espacio. «Simular» muestra antes qué va a pasar, sin cambiar nada.

**Para tener en cuenta:**
- El cupo de documentos y megas es uno solo para toda la demo. Lo que no entra se informa y no se sube.
- Cambiar un archivo con el mismo nombre no lo vuelve a subir. Para reemplazarlo, borralo, sincronizá y volvé a copiarlo.
- La carpeta elegida queda guardada para la próxima vez.
- El modo demo funciona solo en la versión de escritorio. La versión web (Docker) corre en el servidor y rechaza a los usuarios de demo.

---

## 🖼️ Descripciones de Imágenes por IA (La parte mágica)
Cuando subes una imagen, el programa usa **Ollama Cloud** para "mirar" la imagen y escribir una descripción textual de ella.

**Requisitos:**
*   Crear una API Key en [ollama.com/settings/keys](https://ollama.com/settings/keys).
*   Configurar la variable de entorno `OLLAMA_API_KEY` con tu clave.
*   El modelo se configura con `OLLAMA_MODEL` (por defecto: `llava:latest`). Para usar modelos cloud, usa el nombre con sufijo `-cloud`, por ejemplo: `kimi-k2.5:cloud`.

**Cómo funciona:**
1. Sueltas `foto_vacaciones.jpg` en una carpeta.
2. El programa envía la imagen a Ollama Cloud y crea un archivo de texto llamado `foto_vacaciones.image_description.txt`.
3. Este archivo contiene una descripción detallada (ej. *"Una foto de alta resolución de una playa arenosa con agua turquesa y palmeras bajo un cielo azul despejado"*).
4. Solo este texto se envía a InfoHub.
5. **El Resultado**: Cuando le preguntes a tu IA de InfoHub sobre "playas", ¡encontrará esta imagen gracias a la descripción!

---

## 🛠️ Solución de Problemas (FAQ)

**"Añadí un archivo, ¡pero no está en InfoHub!"**
*   Verifica que el archivo esté en una **subcarpeta**. Si está en la raíz de la carpeta `Infohub`, será ignorado.
*   Asegúrate de que el nombre de tu carpeta principal empiece con `Infohub` o `AnythingLLM`.
*   Haz clic en el botón **"Full Upload"** en el Panel Web para forzar la sincronización.

**"Tengo una subcarpeta dentro de un proyecto, ¿se sube?"**
*   Sí. Las subcarpetas dentro de un workspace se suben como archivos internos y el nombre de la carpeta se conserva con el separador `__`: `Sub/archivo.pdf` $\rightarrow$ `Sub__archivo.pdf`.
*   InfoHub no admite carpetas anidadas reales; por eso el nombre de la carpeta se guarda dentro del nombre del archivo. Dos subcarpetas distintas con el mismo nombre de archivo ya no se pisan.
*   Los archivos `.image_description` y `.image_description.txt` están excluidos y nunca se suben.

**"Las imágenes no tienen descripciones."**
*   Verifica que la variable `OLLAMA_API_KEY` esté configurada con una clave válida de [ollama.com](https://ollama.com/settings/keys).
*   Verifica que la configuración `IMAGE_DESCRIPTION_ACTIVATE` esté establecida en `true`.
*   Revisa los logs para ver si hay errores de conexión con Ollama Cloud.

**"Borré un archivo en mi computadora, pero sigue apareciendo en InfoHub."**
*   Ejecuta la operación **"Full Upload and Cleaning"**. Esto sincronizará las eliminaciones de tu disco local hacia la nube.

---

## 📝 Tabla de Resumen Rápido
| Objetivo | Acción |
| :--- | :--- |
| **Añadir nuevos archivos** | Ponerlos en una subcarpeta $\rightarrow$ Clic en "Full Upload" |
| **Actualizar un archivo** | Sobrescribir el archivo en el disco $\rightarrow$ Clic en "Full Upload" |
| **Eliminar un archivo** | Borrarlo del disco $\rightarrow$ Clic en "Full Upload" |
| **Subcarpetas dentro de un proyecto** | Crearlas con sus archivos $\rightarrow$ Clic en "Full Upload" (se guardan como `Carpeta__archivo.ext`) |
| **Crear un nuevo espacio de trabajo** | Crear una nueva subcarpeta $\rightarrow$ Clic en "Full Upload" |
| **Mejorar búsqueda de imágenes** | Clic en "Create Image Descriptions" |
