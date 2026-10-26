# 🎄 Bot del Calendario de Adviento Trendy

Revisa cada 2 horas el catálogo de **maquillajetrendyshop.com** y **Novaventa**. Cuando cambia algo, avisa por **Telegram**: si el calendario se publica, si entra o se agota el stock, si cambia el precio, si hay un descuento o si se revela el contenido. También mantiene una **página web** con el estado y el historial.

Funciona gratis en GitHub y no necesita ningún computador encendido. Tampoco depende de Claude.

---

## Instalación (unos 15 minutos, una sola vez)

### 1. Crear el bot de Telegram
1. En Telegram, busca **@BotFather** y escríbele `/newbot`.
2. Ponle un nombre, por ejemplo `Calendario Trendy`, y un usuario que termine en `bot`, por ejemplo `calendario_trendy_ana_bot`.
3. BotFather te responde con un **token** parecido a `7123456789:AAH...`. Guárdalo.

### 2. Obtener el chat_id de cada persona que recibirá avisos
1. Cada persona abre el bot recién creado en Telegram y le escribe cualquier cosa, por ejemplo «hola».
2. En el navegador, abre esta dirección reemplazando `TOKEN` por el token del paso 1:
   `https://api.telegram.org/botTOKEN/getUpdates`
3. Busca `"chat":{"id":123456789` en el resultado. Ese número es el **chat_id**. Si escribieron varias personas, habrá un número para cada una.

### 3. Subir el bot a GitHub
1. Crea una cuenta gratis en <https://github.com> si no tienes una.
2. Crea un repositorio nuevo, por ejemplo `trendy-bot`. Debe ser **público** para que la página web funcione gratis.
3. Elige **«uploading an existing file»** y arrastra todo el contenido de esta carpeta, incluida la carpeta `.github`.
   - Si la carpeta `.github` no se sube porque está oculta, crea el archivo a mano: **Add file → Create new file**, escribe el nombre `.github/workflows/rastreo.yml` y pega el contenido del archivo `rastreo.yml`.

### 4. Guardar el token y los chat_id
En el repositorio ve a **Settings → Secrets and variables → Actions → New repository secret** y crea estos dos secretos:

| Nombre | Valor |
|---|---|
| `TELEGRAM_TOKEN` | el token del paso 1 |
| `TELEGRAM_CHAT_IDS` | los chat_id separados por comas, por ejemplo `123456789,987654321` |

### 5. Permitir que el bot guarde su estado
**Settings → Actions → General → Workflow permissions** → marca **Read and write permissions** → Save.

### 6. Activar la página web
**Settings → Pages** → en *Source* elige **Deploy from a branch**, branch **main** y carpeta **/docs** → Save.
La página quedará en `https://TU-USUARIO.github.io/trendy-bot/` y ese es el enlace para compartir. Puede tardar unos minutos en aparecer la primera vez.

### 7. Probarlo
**Actions → Rastreo calendario Trendy → Run workflow**. En uno o dos minutos debe llegar a Telegram el mensaje «🤖 Bot del Calendario Trendy activado» con el estado actual.
Desde ahí sigue revisando solo, cada 2 horas.

---

## Preguntas frecuentes

**¿Avisa cada 2 horas aunque no pase nada?** No. Solo escribe cuando hay un cambio. La excepción es si no puede leer una tienda 4 veces seguidas: en ese caso manda una alerta para que sepas que algo cambió en el sitio.

**¿Puede fallar?** Sí, por estas razones:
- Lee el catálogo público de la plataforma de la tienda (VTEX). Si Trendy cambia su web o bloquea estas consultas, el bot lo avisa con la alerta de error.
- Los anuncios que solo salen en TikTok o Instagram, antes de que exista la ficha en la web, **no los detecta**. Conviene activar también las notificaciones de @trendyshopbta.
- GitHub puede retrasar las ejecuciones programadas algunos minutos.

**¿Cómo agrego a otra persona?** Esa persona le escribe al bot, sacas su chat_id con el paso 2 y lo añades con una coma en el secreto `TELEGRAM_CHAT_IDS`.

**¿Cómo lo apago?** **Actions → Rastreo calendario Trendy → ⋯ → Disable workflow**, o borra el repositorio.

**Seguridad:** el único canal oficial de venta de Trendy es su página web. Desconfía de las «preventas» por WhatsApp o redes que no vengan de la marca.
