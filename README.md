# Jumbo Cart Bot

Bot que arma tu carrito de supermercado en [jumbo.com.ar](https://www.jumbo.com.ar) automáticamente. Leés la lista de compras en `cart_items.json`, busca cada producto en el sitio y lo agrega al carrito con la cantidad indicada.

---

## Cómo funciona

### Flujo general

```
cart_items.json
      │
      ▼
  Leer lista
      │
      ▼
  Login / restaurar sesión
      │
      ▼
  Por cada item habilitado:
  ┌─────────────────────────────┐
  │  1. Buscar en jumbo.com.ar  │
  │  2. Elegir mejor resultado  │
  │  3. Agregar al carrito      │
  │  4. Ajustar cantidad        │
  └─────────────────────────────┘
      │
      ▼
  Guardar log con resultados
```

### 1. Sesión y login

El bot usa [Playwright](https://playwright.dev/python/) para controlar un navegador Chromium real. Así puede interactuar con el sitio exactamente como lo haría una persona.

Para no tener que hacer login en cada run, guarda las cookies de sesión en `cookies.json`. Al iniciar, intenta restaurar esa sesión. Si tiene menos de 12 horas y sigue válida, la reutiliza sin volver a loguearse. Si expiró o no existe, hace el login con las credenciales de `.env`.

Si detecta un CAPTCHA durante el login, guarda un screenshot y sale con código `2` para que puedas intervenir manualmente.

### 2. Búsqueda de productos

Para cada item de la lista, el bot navega a la página de búsqueda de Jumbo (`/busca/?q=...`) usando el campo `name` del item. Por ejemplo, para `"Leche La Serenísima Entera 1L"` va a:

```
https://www.jumbo.com.ar/busca/?q=Leche+La+Serenísima+Entera+1L
```

De los primeros resultados (configurable con `max_search_results_to_consider`), elige el que mejor coincide con el nombre usando **matching fuzzy** (algoritmo `token_sort_ratio` de la librería `rapidfuzz`). Esto hace que funcione aunque el nombre exacto del producto en Jumbo sea levemente distinto al que escribiste.

Si no encuentra nada por encima del umbral de similitud (`fuzzy_match_threshold: 60`), intenta de nuevo con `fallback_search` si está definido. Si tampoco funciona, lo registra como `NOT_FOUND` y sigue con el siguiente.

### 3. Agregar al carrito

Una vez encontrado el producto, el bot hace clic en el botón "Agregar al carrito" del resultado y luego ajusta la cantidad usando el botón `+` tantas veces como sea necesario.

Si el producto está sin stock, lo registra como `OUT_OF_STOCK` y continúa. Si el click falla, reintenta hasta `add_to_cart_retry_attempts` veces antes de marcarlo como `ADD_FAILED`.

### Comportamiento humano (anti-bot)

Para evitar ser bloqueado, el bot introduce delays aleatorios:

- 50–150 ms entre cada letra al tipear
- 300–700 ms antes de cada click
- 1.5–4 s entre item e item

### 4. Logs

Al terminar guarda un log en `logs/run_YYYYMMDD_HHMMSS.log` con un resumen legible y un bloque JSON al final con el resultado de cada item. Ese JSON es el que Claude puede leer para detectar qué falló y ajustar la lista.

---

## Estructura del proyecto

```
Claude-Jumbo/
├── bot.py               # Script principal
├── cart_items.json      # Tu lista de compras
├── requirements.txt     # Dependencias Python
├── .env.example         # Template de credenciales
├── .env                 # Tus credenciales (NO se commitea)
├── .gitignore
├── README.md
├── cookies.json         # Sesión guardada (auto-generado, NO se commitea)
└── logs/                # Logs por run (NO se commitean)
```

---

## Instalación

```bash
pip install -r requirements.txt
playwright install chromium
```

## Configuración

```bash
cp .env.example .env
```

Editá `.env`:

```
JUMBO_EMAIL=tu_email@ejemplo.com
JUMBO_PASSWORD=tu_contraseña
```

---

## Uso

```bash
# Ejecutar normalmente (sin ventana)
python bot.py

# Ver el navegador en acción (útil para depurar o el primer login)
python bot.py --visible

# Verificar la lista sin abrir el browser
python bot.py --dry-run

# Forzar login nuevo ignorando la sesión guardada
python bot.py --no-cache

# Usar un archivo de items distinto
python bot.py --items lista_alternativa.json
```

---

## Lista de compras (`cart_items.json`)

```json
{
  "config": {
    "store_url": "https://www.jumbo.com.ar",
    "max_search_results_to_consider": 5,
    "add_to_cart_retry_attempts": 2,
    "fuzzy_match_threshold": 60
  },
  "items": [
    {
      "id": "item-001",
      "name": "Leche La Serenísima Entera 1L",
      "quantity": 4,
      "category": "Lácteos",
      "notes": "Preferir La Serenísima entera 1L",
      "enabled": true,
      "fallback_search": "Leche entera 1L"
    }
  ]
}
```

| Campo | Descripción |
|---|---|
| `id` | Identificador único (no cambiar) |
| `name` | Nombre del producto — lo que el bot busca en Jumbo |
| `quantity` | Cantidad a agregar |
| `category` | Categoría (solo informativo) |
| `notes` | Notas de preferencias o sustituciones |
| `enabled` | `false` para desactivar el item sin borrarlo |
| `fallback_search` | Búsqueda alternativa si la principal no encuentra nada |

**Tip:** Cuanto más específico sea `name` (marca, gramaje, variedad), mejor funciona el matching. Si un item aparece como `NOT_FOUND`, probá con un nombre más genérico o usá `fallback_search`.

---

## Resultados de cada run

| Estado | Significado |
|---|---|
| `SUCCESS` | Agregado al carrito correctamente |
| `NOT_FOUND` | No se encontró el producto |
| `OUT_OF_STOCK` | Encontrado pero sin stock |
| `ADD_FAILED` | Encontrado pero no se pudo agregar |

Los screenshots de errores y CAPTCHAs se guardan automáticamente en `logs/`.

---

## Ejecución automática (cron)

```bash
crontab -e

# Todos los viernes a las 9am:
0 9 * * 5 cd /home/user/Claude-Jumbo && python3 bot.py >> logs/cron.log 2>&1
```

| Código de salida | Significado |
|---|---|
| `0` | Terminó OK (puede haber items fallidos, ver log) |
| `1` | Error de config o credenciales |
| `2` | CAPTCHA — requiere intervención manual |
| `3` | Error inesperado |

---

## Modificar la lista con Claude

`cart_items.json` es el archivo central del sistema. Claude puede editarlo directamente a partir de instrucciones en lenguaje natural:

- *"Agregá 2 paquetes de fideos Matarazzo 500g"*
- *"Sacá el detergente"*
- *"Cambiá la leche a 6"*
- *"La leche no se encontró en el último run, probá con otra búsqueda"*

Claude también puede leer los logs para ver qué falló y ajustar los nombres o `fallback_search` automáticamente.

---

## Solución de problemas

**CAPTCHA (exit code 2):** Esperá unas horas y reintentá. La primera vez conviene correr con `--visible` para poder resolver el CAPTCHA manualmente si aparece.

**Item no encontrado:** Probá un nombre más simple en `name` o definí un `fallback_search` más genérico. El umbral de matching se puede bajar en `config.fuzzy_match_threshold` (default: 60).

**Selectores rotos:** Si Jumbo actualiza su sitio y el bot deja de funcionar, todos los selectores CSS están agrupados en el dict `SELECTORS` al principio de `bot.py`. Basta con actualizar ese dict.

**Sesión expirada:** Las cookies se reutilizan por 12 horas. Usá `--no-cache` para forzar un login nuevo.
