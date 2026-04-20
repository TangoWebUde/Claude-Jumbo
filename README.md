# Jumbo Cart Bot

Bot que arma tu carrito de supermercado en [jumbo.com.ar](https://www.jumbo.com.ar) automáticamente a partir de una lista de items configurada en `cart_items.json`.

## Requisitos

- Python 3.10+
- Cuenta en jumbo.com.ar

## Instalación

```bash
pip install -r requirements.txt
playwright install chromium
```

## Configuración

1. Copiá el template de credenciales:

```bash
cp .env.example .env
```

2. Editá `.env` con tu email y contraseña de Jumbo:

```
JUMBO_EMAIL=tu_email@ejemplo.com
JUMBO_PASSWORD=tu_contraseña
```

## Uso

```bash
# Ejecutar normalmente (headless)
python bot.py

# Ver el navegador mientras funciona (útil para depurar)
python bot.py --visible

# Validar la lista de items sin abrir el browser
python bot.py --dry-run

# Forzar login nuevo (ignorar sesión guardada)
python bot.py --no-cache

# Usar un archivo de items alternativo
python bot.py --items otra_lista.json
```

## Lista de compras (`cart_items.json`)

Editá `cart_items.json` para configurar qué productos agregar al carrito.

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
      "notes": "Preferir La Serenísima entera",
      "enabled": true,
      "fallback_search": "Leche entera 1L"
    }
  ]
}
```

### Campos

| Campo | Descripción |
|---|---|
| `id` | Identificador único del item |
| `name` | Nombre del producto (se usa para buscar en Jumbo) |
| `quantity` | Cantidad a agregar al carrito |
| `category` | Categoría (informativo) |
| `notes` | Notas sobre preferencias o sustituciones |
| `enabled` | `true` para incluir, `false` para desactivar sin borrar |
| `fallback_search` | Búsqueda alternativa si la principal no encuentra nada |

**Tip:** Usá `"enabled": false` para desactivar items temporalmente sin perder su configuración.

## Resultados

El bot guarda un log en `logs/run_YYYYMMDD_HHMMSS.log` con el resultado de cada item:

- `SUCCESS` — agregado al carrito correctamente
- `NOT_FOUND` — no se encontró el producto
- `OUT_OF_STOCK` — sin stock
- `ADD_FAILED` — se encontró pero no se pudo agregar

Si hay un error o CAPTCHA, se guarda un screenshot en `logs/`.

## Ejecución automática (cron)

Para ejecutar automáticamente todos los viernes a las 9am:

```bash
# Editar crontab
crontab -e

# Agregar esta línea (ajustá la ruta):
0 9 * * 5 cd /home/user/Claude-Jumbo && python3 bot.py >> logs/cron.log 2>&1
```

### Códigos de salida

| Código | Significado |
|---|---|
| `0` | OK (puede haber items no encontrados, ver log) |
| `1` | Error de configuración o login |
| `2` | CAPTCHA detectado — requiere intervención manual |
| `3` | Error inesperado |

## Modificar la lista con Claude

Podés pedirle a Claude que modifique `cart_items.json` con lenguaje natural:

- *"Agregá 2 paquetes de fideos Matarazzo 500g"*
- *"Sacá el detergente de la lista"*
- *"Cambiá la cantidad de leche a 6"*
- *"El yogur no se encontró en el último run, probá con otra búsqueda"*

Claude también puede leer los logs para ver qué items fallaron y ajustar la lista automáticamente.

## Solución de problemas

**CAPTCHA (exit code 2):** Jumbo detectó el bot. Esperá unas horas y volvé a intentar. También podés ejecutar con `--visible` para hacer el login manualmente la primera vez.

**Selectores rotos:** Si Jumbo actualiza su sitio, los selectores CSS en `bot.py` pueden dejar de funcionar. Están todos agrupados en el dict `SELECTORS` al principio del archivo para facilitar la actualización.

**Sesión expirada:** El bot guarda las cookies en `cookies.json` y las reutiliza por 12 horas. Podés forzar un login nuevo con `--no-cache`.
