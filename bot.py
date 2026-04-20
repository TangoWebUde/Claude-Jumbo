#!/usr/bin/env python3
"""Jumbo.com.ar cart automation bot."""

import argparse
import json
import os
import random
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright
from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# Selectors — update here if Jumbo's markup changes
# ---------------------------------------------------------------------------
SELECTORS = {
    "search_input": (
        "input[class*='searchbar'], "
        "[data-testid='open-search'], "
        "input[placeholder*='Buscar'], "
        "input[placeholder*='buscar']"
    ),
    "search_submit": "button[type='submit'][class*='search'], [class*='searchButton']",
    "product_card": (
        ".vtex-product-summary-2-x-container, "
        "[class*='productSummary'], "
        "[class*='product-summary']"
    ),
    "product_name": (
        "[class*='productNameContainer'], "
        "[class*='productName'], "
        "h3[class*='name'], "
        "span[class*='productBrand']"
    ),
    "add_to_cart_btn": (
        "[class*='buyButton']:not([class*='unavailable']):not([class*='disabled']), "
        "button[class*='add-to-cart']:not([disabled])"
    ),
    "out_of_stock": (
        "[class*='buyButton--unavailable'], "
        "[class*='unavailable'], "
        "button[disabled][class*='buy']"
    ),
    "qty_increment": (
        "[class*='quantitySelector'] button:last-child, "
        "[class*='quantity-selector'] button:last-child, "
        "[class*='incrementButton']"
    ),
    "cart_counter": (
        "[class*='minicart'] [class*='badge'], "
        "[class*='minicartCounter'], "
        "[data-testid='minicart-badge']"
    ),
    "logged_in_indicator": (
        "[class*='profile'] span, "
        "a[href*='/account'], "
        "[class*='accountMenu']"
    ),
    "login_email": "input[name='email'], input[type='email'], #username",
    "login_password": "input[name='password'], input[type='password'], #password",
    "login_submit": "button[type='submit'], button[class*='login']",
    "captcha_frame": "iframe[src*='recaptcha'], iframe[src*='captcha']",
    "address_modal": "[class*='addressModal'], [class*='location-modal']",
    "address_modal_close": "[class*='addressModal'] button[class*='close'], [class*='location-modal'] button",
    "cart_item_row": (
        "[class*='CartItem'], [class*='cartItem'], "
        "[class*='cart-item'], [class*='minicartItem']"
    ),
    "cart_item_name": (
        "[class*='productName'], [class*='ProductName'], "
        "[class*='nameContainer'], span[class*='name']"
    ),
    "cart_item_qty": (
        "input[class*='Quantity'], input[class*='quantity'], "
        "[class*='quantityInput'], [class*='quantity-input']"
    ),
}

PRESETS_DIR = Path("presets")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    name: str
    selector_index: int
    available: bool
    score: float = 0.0


@dataclass
class ItemResult:
    item_id: str
    name: str
    status: str  # success | not_found | out_of_stock | add_failed | skipped
    matched_name: str = ""
    quantity_added: int = 0
    error_msg: str = ""


@dataclass
class RunReport:
    timestamp: str
    succeeded: int = 0
    failed: int = 0
    not_found: int = 0
    out_of_stock: int = 0
    skipped: int = 0
    item_results: list = field(default_factory=list)

    def summary(self) -> str:
        total = self.succeeded + self.failed + self.not_found + self.out_of_stock
        lines = [
            f"Run: {self.timestamp}",
            f"  OK:          {self.succeeded}",
            f"  No encontrado: {self.not_found}",
            f"  Sin stock:   {self.out_of_stock}",
            f"  Error:       {self.failed}",
            f"  Saltados:    {self.skipped}",
            f"  Total:       {total}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class JumboBot:
    BASE_URL = "https://www.jumbo.com.ar"

    def __init__(self, items_path: str | None = None, headless: bool = True, no_cache: bool = False):
        load_dotenv()
        self.email = os.getenv("JUMBO_EMAIL")
        self.password = os.getenv("JUMBO_PASSWORD")
        if not self.email or not self.password:
            _die(
                "Faltan credenciales. Copia .env.example a .env y completá "
                "JUMBO_EMAIL y JUMBO_PASSWORD.",
                exit_code=1,
            )

        if items_path:
            self.items_path = Path(items_path)
            self.config, self.items = self._load_items()
        else:
            self.items_path = None
            self.config, self.items = {}, []
        self.store_url = self.config.get("store_url", self.BASE_URL)
        self.max_results = self.config.get("max_search_results_to_consider", 5)
        self.retry_attempts = self.config.get("add_to_cart_retry_attempts", 2)
        self.fuzzy_threshold = self.config.get("fuzzy_match_threshold", 60)

        self.headless = headless
        self.no_cache = no_cache
        self.cookies_path = Path("cookies.json")
        self.logs_dir = Path("logs")
        self.logs_dir.mkdir(exist_ok=True)

        self._playwright = None
        self._browser = None
        self.page: Page = None

    # ------------------------------------------------------------------
    # Startup / teardown
    # ------------------------------------------------------------------

    def start(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context_kwargs = {
            "viewport": {"width": 1280, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "locale": "es-AR",
        }

        if not self.no_cache and self.cookies_path.exists():
            age_hours = (time.time() - self.cookies_path.stat().st_mtime) / 3600
            if age_hours < 12:
                context_kwargs["storage_state"] = str(self.cookies_path)

        self._context = self._browser.new_context(**context_kwargs)
        self.page = self._context.new_page()

    def close(self):
        if self._context:
            try:
                self._context.storage_state(path=str(self.cookies_path))
            except Exception:
                pass
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    def ensure_logged_in(self):
        self.page.goto(self.store_url, wait_until="domcontentloaded")
        self._human_delay(1000, 2000)
        self._dismiss_address_modal()

        if self._is_logged_in():
            print("[sesión] Sesión activa desde cookies.")
            return

        print("[sesión] Iniciando sesión...")
        self._login()

    def _is_logged_in(self) -> bool:
        try:
            el = self.page.locator(SELECTORS["logged_in_indicator"]).first
            return el.is_visible(timeout=3000)
        except Exception:
            return False

    def _login(self):
        login_url = f"{self.store_url}/login"
        self.page.goto(login_url, wait_until="domcontentloaded")
        self._human_delay(1000, 2000)

        # Fill email
        email_input = self.page.locator(SELECTORS["login_email"]).first
        email_input.wait_for(state="visible", timeout=10000)
        self._type_human(email_input, self.email)
        self._human_delay(400, 800)

        # Some VTEX logins have a separate "Continue" step before password
        try:
            continue_btn = self.page.locator("button[class*='continue'], button:has-text('Continuar')").first
            if continue_btn.is_visible(timeout=2000):
                continue_btn.click()
                self._human_delay(800, 1500)
        except Exception:
            pass

        # Fill password
        pwd_input = self.page.locator(SELECTORS["login_password"]).first
        pwd_input.wait_for(state="visible", timeout=10000)
        self._type_human(pwd_input, self.password)
        self._human_delay(500, 1000)

        # Check for CAPTCHA before submitting
        if self._captcha_present():
            screenshot_path = self._save_screenshot("captcha")
            _die(
                f"CAPTCHA detectado antes del login. Resolvelo manualmente.\n"
                f"Screenshot guardado en: {screenshot_path}",
                exit_code=2,
            )

        submit_btn = self.page.locator(SELECTORS["login_submit"]).first
        submit_btn.click()
        self._human_delay(2000, 4000)

        # Verify login success
        if not self._is_logged_in():
            # Give one more chance — some VTEX sites redirect slowly
            self._human_delay(2000, 3000)
            if not self._is_logged_in():
                if self._captcha_present():
                    screenshot_path = self._save_screenshot("captcha_post_login")
                    _die(
                        f"CAPTCHA detectado tras intentar login.\n"
                        f"Screenshot guardado en: {screenshot_path}",
                        exit_code=2,
                    )
                screenshot_path = self._save_screenshot("login_failed")
                _die(
                    f"Login fallido. Verificá las credenciales en .env.\n"
                    f"Screenshot guardado en: {screenshot_path}",
                    exit_code=1,
                )

        print("[sesión] Login exitoso.")
        self._context.storage_state(path=str(self.cookies_path))

    def _captcha_present(self) -> bool:
        try:
            return self.page.locator(SELECTORS["captcha_frame"]).first.is_visible(timeout=1500)
        except Exception:
            return False

    def _dismiss_address_modal(self):
        try:
            modal = self.page.locator(SELECTORS["address_modal"]).first
            if modal.is_visible(timeout=2000):
                close_btn = self.page.locator(SELECTORS["address_modal_close"]).first
                close_btn.click()
                self._human_delay(500, 1000)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Read current cart
    # ------------------------------------------------------------------

    def read_cart(self) -> list[dict]:
        """Navigate to the cart page and return the items currently in it."""
        cart_url = f"{self.store_url}/checkout/#/cart"
        print(f"[carrito] Leyendo carrito en {cart_url} ...")
        self.page.goto(cart_url, wait_until="domcontentloaded")
        self._human_delay(2000, 3500)
        self._dismiss_address_modal()
        items = self._items_from_cart()
        print(f"[carrito] {len(items)} producto(s) encontrado(s).")
        return items

    def _items_from_cart(self) -> list[dict]:
        rows = self.page.locator(SELECTORS["cart_item_row"])
        count = rows.count()
        items = []
        for i in range(count):
            row = rows.nth(i)
            try:
                name = row.locator(SELECTORS["cart_item_name"]).first.inner_text(timeout=2000).strip()
            except Exception:
                name = f"Producto #{i + 1}"

            qty = 1
            try:
                qty_el = row.locator(SELECTORS["cart_item_qty"]).first
                qty_val = qty_el.input_value(timeout=1000).strip()
                qty = int(qty_val) if qty_val.isdigit() else 1
            except Exception:
                pass

            items.append({
                "id": f"item-{i + 1:03d}",
                "name": name,
                "quantity": qty,
                "category": "",
                "notes": None,
                "enabled": True,
                "fallback_search": None,
            })
        return items

    # ------------------------------------------------------------------
    # Search & add to cart
    # ------------------------------------------------------------------

    def process_item(self, item: dict) -> ItemResult:
        item_id = item["id"]
        name = item["name"]
        quantity = item.get("quantity", 1)
        fallback = item.get("fallback_search")

        for query in _unique([name, fallback]):
            if not query:
                continue
            results = self._search(query)
            match = self._best_match(results, name)
            if match:
                break
        else:
            return ItemResult(item_id=item_id, name=name, status="not_found")

        if not match.available:
            return ItemResult(item_id=item_id, name=name, status="out_of_stock", matched_name=match.name)

        success = self._add_to_cart(match, quantity)
        if success:
            return ItemResult(
                item_id=item_id,
                name=name,
                status="success",
                matched_name=match.name,
                quantity_added=quantity,
            )
        return ItemResult(item_id=item_id, name=name, status="add_failed", matched_name=match.name)

    def _search(self, query: str) -> list[SearchResult]:
        try:
            search_url = f"{self.store_url}/busca/?q={query.replace(' ', '+')}"
            self.page.goto(search_url, wait_until="domcontentloaded")
            self._human_delay(1500, 3000)
            self._dismiss_address_modal()

            cards = self.page.locator(SELECTORS["product_card"])
            count = min(cards.count(), self.max_results)
            results = []

            for i in range(count):
                card = cards.nth(i)
                try:
                    name_el = card.locator(SELECTORS["product_name"]).first
                    product_name = name_el.inner_text(timeout=2000).strip()
                except Exception:
                    product_name = f"Producto #{i}"

                out_of_stock = False
                try:
                    oos = card.locator(SELECTORS["out_of_stock"]).first
                    out_of_stock = oos.is_visible(timeout=500)
                except Exception:
                    pass

                results.append(SearchResult(
                    name=product_name,
                    selector_index=i,
                    available=not out_of_stock,
                ))

            return results
        except Exception as e:
            print(f"  [búsqueda] Error buscando '{query}': {e}")
            return []

    def _best_match(self, results: list[SearchResult], target: str) -> SearchResult | None:
        best = None
        best_score = 0.0
        for r in results:
            score = fuzz.token_sort_ratio(target.lower(), r.name.lower())
            if score > best_score:
                best_score = score
                r.score = score
                best = r
        if best and best_score >= self.fuzzy_threshold:
            return best
        return None

    def _add_to_cart(self, result: SearchResult, quantity: int) -> bool:
        for attempt in range(self.retry_attempts):
            try:
                cards = self.page.locator(SELECTORS["product_card"])
                card = cards.nth(result.selector_index)
                add_btn = card.locator(SELECTORS["add_to_cart_btn"]).first
                add_btn.wait_for(state="visible", timeout=5000)
                self._human_delay(300, 700)
                add_btn.click()
                self._human_delay(800, 1500)

                # Increase quantity if needed
                if quantity > 1:
                    inc_btn = card.locator(SELECTORS["qty_increment"]).first
                    for _ in range(quantity - 1):
                        inc_btn.wait_for(state="visible", timeout=3000)
                        inc_btn.click()
                        self._human_delay(300, 700)

                return True
            except Exception as e:
                print(f"  [carrito] Intento {attempt + 1} fallido: {e}")
                self._human_delay(1000, 2000)

        return False

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(self) -> RunReport:
        report = RunReport(timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        enabled = [it for it in self.items if it.get("enabled", True)]
        disabled = [it for it in self.items if not it.get("enabled", True)]
        report.skipped = len(disabled)

        print(f"\n=== Jumbo Bot — {report.timestamp} ===")
        print(f"Items habilitados: {len(enabled)} | Desactivados: {len(disabled)}\n")

        for item in enabled:
            print(f"[{item['id']}] Procesando: {item['name']} (x{item.get('quantity', 1)})")
            try:
                result = self.process_item(item)
            except Exception as e:
                screenshot = self._save_screenshot(f"error_{item['id']}")
                print(f"  Error inesperado: {e}")
                print(f"  Screenshot: {screenshot}")
                result = ItemResult(
                    item_id=item["id"],
                    name=item["name"],
                    status="add_failed",
                    error_msg=str(e),
                )

            report.item_results.append(result)
            status_map = {
                "success": "succeeded",
                "not_found": "not_found",
                "out_of_stock": "out_of_stock",
                "add_failed": "failed",
                "skipped": "skipped",
            }
            attr = status_map.get(result.status, "failed")
            setattr(report, attr, getattr(report, attr) + 1)

            _print_result(result)
            self._human_delay(1500, 4000)

        self._save_log(report)
        print(f"\n{report.summary()}\n")
        return report

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_items(self):
        try:
            data = json.loads(self.items_path.read_text(encoding="utf-8"))
            return data.get("config", {}), data.get("items", [])
        except json.JSONDecodeError as e:
            _die(f"Error en cart_items.json: {e}", exit_code=1)
        except FileNotFoundError:
            _die(f"Archivo no encontrado: {self.items_path}", exit_code=1)

    def _type_human(self, locator, text: str):
        locator.click()
        for char in text:
            locator.press(char)
            time.sleep(random.uniform(0.05, 0.15))

    def _human_delay(self, min_ms: int = 500, max_ms: int = 1500):
        time.sleep(random.uniform(min_ms, max_ms) / 1000)

    def _save_screenshot(self, name: str) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.logs_dir / f"{name}_{ts}.png"
        try:
            self.page.screenshot(path=str(path))
        except Exception:
            pass
        return str(path)

    def _save_log(self, report: RunReport):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = self.logs_dir / f"run_{ts}.log"
        lines = [report.summary(), "", "--- Detalle ---"]
        for r in report.item_results:
            lines.append(
                f"  {r.status.upper():12} {r.name}"
                + (f"  →  {r.matched_name}" if r.matched_name else "")
                + (f"  (x{r.quantity_added})" if r.quantity_added else "")
                + (f"  ERROR: {r.error_msg}" if r.error_msg else "")
            )
        lines += ["", "--- JSON ---", json.dumps(
            {
                "timestamp": report.timestamp,
                "succeeded": report.succeeded,
                "not_found": report.not_found,
                "out_of_stock": report.out_of_stock,
                "failed": report.failed,
                "skipped": report.skipped,
                "items": [
                    {
                        "id": r.item_id,
                        "name": r.name,
                        "status": r.status,
                        "matched_name": r.matched_name,
                        "quantity_added": r.quantity_added,
                        "error_msg": r.error_msg,
                    }
                    for r in report.item_results
                ],
            },
            ensure_ascii=False,
            indent=2,
        )]
        log_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"[log] Guardado en: {log_path}")


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG = {
    "store_url": "https://www.jumbo.com.ar",
    "max_search_results_to_consider": 5,
    "add_to_cart_retry_attempts": 2,
    "fuzzy_match_threshold": 60,
}


def save_preset(name: str, items: list[dict], config: dict | None = None) -> Path:
    PRESETS_DIR.mkdir(exist_ok=True)
    preset_path = PRESETS_DIR / f"{name}.json"
    data = {"config": config or _DEFAULT_CONFIG, "items": items}
    preset_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return preset_path


def load_preset(name: str) -> tuple[dict, list]:
    preset_path = PRESETS_DIR / f"{name}.json"
    if not preset_path.exists():
        available = list_presets()
        hint = f"Disponibles: {', '.join(available)}" if available else "No hay presets guardados aún."
        _die(f"Preset '{name}' no encontrado. {hint}")
    try:
        data = json.loads(preset_path.read_text(encoding="utf-8"))
        return data.get("config", {}), data.get("items", [])
    except json.JSONDecodeError as e:
        _die(f"Error leyendo preset '{name}': {e}")


def list_presets() -> list[str]:
    if not PRESETS_DIR.exists():
        return []
    return [p.stem for p in sorted(PRESETS_DIR.glob("*.json"))]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _die(msg: str, exit_code: int = 1):
    print(f"\n[ERROR] {msg}", file=sys.stderr)
    sys.exit(exit_code)


def _print_result(r: ItemResult):
    icons = {"success": "✓", "not_found": "✗", "out_of_stock": "~", "add_failed": "!", "skipped": "-"}
    icon = icons.get(r.status, "?")
    msg = f"  {icon} {r.status}"
    if r.matched_name:
        msg += f" → {r.matched_name}"
    if r.quantity_added:
        msg += f" (x{r.quantity_added})"
    if r.error_msg:
        msg += f" — {r.error_msg}"
    print(msg)


def _unique(lst: list) -> list:
    seen = set()
    return [x for x in lst if x and not (x in seen or seen.add(x))]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Jumbo.com.ar cart automation bot")
    parser.add_argument("--visible", action="store_true", help="Mostrar ventana del navegador")
    parser.add_argument("--dry-run", action="store_true", help="Validar JSON y mostrar items sin abrir browser")
    parser.add_argument("--no-cache", action="store_true", help="Ignorar cookies guardadas, forzar login")
    parser.add_argument("--items", default="cart_items.json", help="Ruta al archivo de items (default: cart_items.json)")
    parser.add_argument("--save-preset", metavar="NOMBRE", help="Leer el carrito actual de Jumbo y guardarlo como preset")
    parser.add_argument("--load-preset", metavar="NOMBRE", help="Usar un preset guardado en lugar de --items")
    parser.add_argument("--list-presets", action="store_true", help="Listar los presets disponibles")
    args = parser.parse_args()

    headless = not args.visible

    if args.list_presets:
        _cmd_list_presets()
        return

    if args.dry_run:
        items_path = _resolve_items_path(args)
        _dry_run(items_path)
        return

    if args.save_preset:
        _cmd_save_preset(args.save_preset, headless=headless, no_cache=args.no_cache)
        return

    items_path = _resolve_items_path(args)
    bot = JumboBot(items_path=items_path, headless=headless, no_cache=args.no_cache)
    try:
        bot.start()
        bot.ensure_logged_in()
        bot.run()
    except SystemExit:
        raise
    except Exception:
        print("\n[ERROR INESPERADO]", file=sys.stderr)
        traceback.print_exc()
        sys.exit(3)
    finally:
        bot.close()

    sys.exit(0)


def _resolve_items_path(args) -> str:
    if args.load_preset:
        preset_path = PRESETS_DIR / f"{args.load_preset}.json"
        if not preset_path.exists():
            available = list_presets()
            hint = f"Disponibles: {', '.join(available)}" if available else "No hay presets guardados aún."
            _die(f"Preset '{args.load_preset}' no encontrado. {hint}")
        print(f"[preset] Usando preset '{args.load_preset}'.")
        return str(preset_path)
    return args.items


def _cmd_list_presets():
    presets = list_presets()
    if not presets:
        print("No hay presets guardados. Usá --save-preset NOMBRE para crear uno.")
        return
    print(f"Presets disponibles ({len(presets)}):")
    for name in presets:
        preset_path = PRESETS_DIR / f"{name}.json"
        try:
            data = json.loads(preset_path.read_text(encoding="utf-8"))
            items = data.get("items", [])
            enabled = sum(1 for it in items if it.get("enabled", True))
            print(f"  {name}  ({enabled} item(s))")
        except Exception:
            print(f"  {name}  (error al leer)")


def _cmd_save_preset(name: str, headless: bool, no_cache: bool):
    bot = JumboBot(headless=headless, no_cache=no_cache)
    try:
        bot.start()
        bot.ensure_logged_in()
        items = bot.read_cart()
    except SystemExit:
        raise
    except Exception:
        print("\n[ERROR INESPERADO]", file=sys.stderr)
        traceback.print_exc()
        sys.exit(3)
    finally:
        bot.close()

    if not items:
        print("[preset] El carrito está vacío. Agregá productos en Jumbo antes de guardar.")
        sys.exit(1)

    preset_path = save_preset(name, items)
    print(f"[preset] Guardado como '{name}' en {preset_path} ({len(items)} item(s)).")
    print("\nProductos guardados:")
    for it in items:
        print(f"  [{it['id']}] {it['name']}  x{it['quantity']}")


def _dry_run(items_path: str):
    path = Path(items_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        _die(f"Error leyendo {items_path}: {e}")

    items = data.get("items", [])
    enabled = [it for it in items if it.get("enabled", True)]
    disabled = [it for it in items if not it.get("enabled", True)]

    print(f"\n=== Dry run: {items_path} ===")
    print(f"Items habilitados ({len(enabled)}):")
    for it in enabled:
        print(f"  [{it['id']}] {it['name']}  x{it.get('quantity', 1)}")
    if disabled:
        print(f"\nItems desactivados ({len(disabled)}):")
        for it in disabled:
            print(f"  [{it['id']}] {it['name']}")
    print()


if __name__ == "__main__":
    main()
