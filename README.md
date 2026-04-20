# Jumbo Cart Bot

Bot que arma tu carrito de supermercado en [jumbo.com.ar](https://www.jumbo.com.ar) automáticamente. Manejás la lista de productos hablando con Claude, y el bot se encarga de buscarlos y agregarlos al carrito por vos.

---

## Qué necesitás

- **Python 3.10 o superior** — [python.org/downloads](https://www.python.org/downloads/)
- **Claude Code** (la CLI de Anthropic) — [instalación](#instalar-claude-code)
- Una cuenta en **jumbo.com.ar**
- Git para clonar el repositorio

---

## Instalación paso a paso

### 1. Clonar el repositorio

```bash
git clone https://github.com/TangoWebUde/Claude-Jumbo.git
cd Claude-Jumbo
```

### 2. Instalar dependencias Python

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Configurar credenciales

```bash
cp .env.example .env
```

Abrí el archivo `.env` con cualquier editor de texto y completá tu email y contraseña de Jumbo:

```
JUMBO_EMAIL=tu_email@ejemplo.com
JUMBO_PASSWORD=tu_contraseña
```

> `.env` nunca se sube al repositorio — es solo tuyo.

### 4. Instalar Claude Code

Claude Code es la interfaz con la que le hablás a Claude desde la terminal para modificar tu lista de compras.

```bash
npm install -g @anthropic-ai/claude-code
```

> Requiere Node.js. Si no lo tenés: [nodejs.org](https://nodejs.org/)

Una vez instalado, autenticarte:

```bash
claude
```

La primera vez te va a pedir que inicies sesión con tu cuenta de Anthropic (la misma de [claude.ai](https://claude.ai)).

---

## Cómo usar el bot

### Paso 1 — Abrí Claude Code en la carpeta del proyecto

```bash
cd Claude-Jumbo
claude
```

Esto abre una sesión de Claude con contexto del proyecto. Desde acá podés pedirle que modifique tu lista de compras.

### Paso 2 — Armá tu lista hablando con Claude

Escribile lo que querés comprar en lenguaje natural. Por ejemplo:

```
Agregá 4 litros de leche La Serenísima entera, 2 panes lactal Bimbo,
1 botella de aceite Cocinero 1.5L y 6 yogures Danone de frutilla.
```

Claude va a editar `cart_items.json` por vos. También podés hacer cambios puntuales:

```
Cambiá la leche a 6 litros.
Sacá el aceite de la lista.
Agregá 1kg de arroz Gallo de Oro.
```

### Paso 3 — Correr el bot

Cuando la lista esté lista, salí de Claude Code (`Ctrl+C` o escribí `exit`) y ejecutá:

```bash
python bot.py
```

El bot va a abrir un navegador (invisible), loguearse en Jumbo, buscar cada producto y agregarlo al carrito. Al terminar, podés entrar a [jumbo.com.ar](https://www.jumbo.com.ar) y ver tu carrito listo para hacer el pedido.

La primera vez te recomendamos correrlo con `--visible` para ver qué hace:

```bash
python bot.py --visible
```

---

## Cómo funciona internamente

```
cart_items.json
      │
      ▼
  Leer lista de compras
      │
      ▼
  Login / restaurar sesión guardada
      │
      ▼
  Por cada producto habilitado:
  ┌────────────────────────────────────┐
  │  1. Buscar en jumbo.com.ar         │
  │  2. Elegir el resultado más similar│
  │  3. Clic en "Agregar al carrito"   │
  │  4. Ajustar cantidad               │
  └────────────────────────────────────┘
      │
      ▼
  Guardar log con resultados
```

**Sesión:** Para no loguearse cada vez, el bot guarda las cookies en `cookies.json` y las reutiliza durante 12 horas.

**Búsqueda:** Por cada producto navega a `jumbo.com.ar/busca/?q=...` y compara los resultados con el nombre usando *matching fuzzy*. Esto tolera diferencias menores entre el nombre que escribiste y el que usa Jumbo.

**Anti-bot:** Para no ser bloqueado, tipea y hace clicks con delays aleatorios simulando comportamiento humano.

**Logs:** Guarda el resultado de cada run en `logs/` con el estado de cada producto.

---

## Comandos disponibles

```bash
python bot.py               # Ejecutar (sin ventana del navegador)
python bot.py --visible     # Mostrar el navegador mientras trabaja
python bot.py --dry-run     # Solo mostrar la lista, sin abrir el browser
python bot.py --no-cache    # Forzar login nuevo (ignorar sesión guardada)
```

---

## Qué pasa con cada producto

| Estado | Significado |
|---|---|
| `SUCCESS` | Agregado al carrito |
| `NOT_FOUND` | No se encontró en Jumbo |
| `OUT_OF_STOCK` | Sin stock |
| `ADD_FAILED` | Se encontró pero no se pudo agregar |

Si un producto aparece como `NOT_FOUND`, podés pedirle a Claude que pruebe con un nombre más simple:

```
El arroz no se encontró, probá con una búsqueda más genérica.
```

Claude va a ajustar la lista y en el próximo run lo va a encontrar.

---

## Ejecución automática (opcional)

Para que el bot corra solo, por ejemplo todos los viernes a las 9am, podés configurar una tarea programada.

**Linux/Mac (cron):**
```bash
crontab -e
# Agregar:
0 9 * * 5 cd /ruta/a/Claude-Jumbo && python3 bot.py >> logs/cron.log 2>&1
```

**Windows (Task Scheduler):** Crear una tarea que ejecute `python bot.py` en la carpeta del proyecto.

---

## Solución de problemas

**El bot no arranca / error de credenciales:** Verificá que `.env` exista y tenga el email y contraseña correctos.

**CAPTCHA:** Jumbo a veces muestra un CAPTCHA. El bot guarda un screenshot en `logs/` y para. Corré con `--visible` para ver qué pasa y, si aparece, resolvelo manualmente. Después volvé a correr normalmente.

**Producto no encontrado:** Pedile a Claude que simplifique el nombre o agregue un `fallback_search`. Cuanto más específico es el nombre (marca, tamaño, variedad), más precisa es la búsqueda, pero si es demasiado específico puede no encontrar nada.

**El bot dejó de funcionar después de una actualización de Jumbo:** El sitio puede cambiar su estructura HTML. Todos los selectores están agrupados en el dict `SELECTORS` al principio de `bot.py` — podés pedirle a Claude que los actualice.

**Sesión expirada:** Si hace más de 12 horas desde el último run, el bot va a loguearse de nuevo automáticamente. Si querés forzar eso, usá `--no-cache`.
