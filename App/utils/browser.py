from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager

from App.config import get_scraper_settings


SUPPORTED_BROWSERS = {"chrome", "firefox", "edge"}
SCRAPER_SETTINGS = get_scraper_settings()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum or value > maximum:
        return default
    return value


def _webdriver_manager_enabled() -> bool:
    return _env_bool("WEBDRIVER_MANAGER_ENABLED", True)


def _normalize_browser_name(name: str) -> str:
    candidate = (name or "").strip().lower()
    aliases = {
        "google-chrome": "chrome",
        "chromium": "chrome",
        "msedge": "edge",
        "microsoft-edge": "edge",
        "edge-chromium": "edge",
        "ff": "firefox",
    }
    return aliases.get(candidate, candidate)


def _parse_browser_list(raw: str | None) -> list[str]:
    if not raw:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        browser = _normalize_browser_name(part)
        if browser not in SUPPORTED_BROWSERS:
            continue
        if browser in seen:
            continue
        seen.add(browser)
        out.append(browser)
    return out


def resolve_browser_pool(remote_url: str | None = None) -> list[str]:
    """
    Resolve lista de navegadores para execucao Selenium.

    Ordem de leitura:
    1) SELENIUM_BROWSERS (CSV)
    2) SELENIUM_BROWSER (single)
    3) autodetect local (chrome, firefox)
    4) fallback = chrome
    """

    pool = _parse_browser_list(os.getenv("SELENIUM_BROWSERS"))
    if pool:
        return pool

    single = _normalize_browser_name(os.getenv("SELENIUM_BROWSER", ""))
    if single in SUPPORTED_BROWSERS:
        return [single]

    if not (remote_url or os.getenv("SELENIUM_REMOTE_URL")):
        autodetected: list[str] = []
        if _find_chrome_binary():
            autodetected.append("chrome")
        if _find_edge_binary():
            autodetected.append("edge")
        if _find_firefox_binary():
            autodetected.append("firefox")
        if autodetected:
            return autodetected

    return ["chrome"]


def _find_chrome_binary() -> str | None:
    env_path = os.getenv("CHROME_BINARY")
    if env_path and Path(env_path).exists():
        return env_path

    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        path = shutil.which(name)
        if path:
            return path

    if sys.platform.startswith("win"):
        candidates = []
        for base in (
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ):
            if not base:
                continue
            candidates.extend(
                [
                    Path(base) / "Google/Chrome/Application/chrome.exe",
                    Path(base) / "Chromium/Application/chrome.exe",
                ]
            )
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

    if sys.platform == "darwin":
        mac_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if Path(mac_path).exists():
            return mac_path

    return None


def _find_edge_binary() -> str | None:
    env_path = os.getenv("EDGE_BINARY")
    if env_path and Path(env_path).exists():
        return env_path

    for name in ("msedge", "microsoft-edge"):
        path = shutil.which(name)
        if path:
            return path

    if sys.platform.startswith("win"):
        candidates = []
        for base in (
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ):
            if not base:
                continue
            candidates.append(Path(base) / "Microsoft/Edge/Application/msedge.exe")
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

    if sys.platform == "darwin":
        mac_path = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
        if Path(mac_path).exists():
            return mac_path

    return None


def _find_firefox_binary() -> str | None:
    env_path = os.getenv("FIREFOX_BINARY")
    if env_path and Path(env_path).exists():
        return env_path

    if sys.platform.startswith("win"):
        candidates = []
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)")):
            if not base:
                continue
            candidates.append(Path(base) / "Mozilla Firefox/firefox.exe")
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

    firefox_path = shutil.which("firefox")
    if firefox_path:
        return firefox_path
    return None


def _resolve_driver_env_path(env_name: str) -> str | None:
    raw = (os.getenv(env_name, "") or "").strip()
    if not raw:
        return None

    candidate = Path(raw)
    if candidate.exists():
        return str(candidate)
    return None


def _ensure_selenium_cache_path() -> None:
    if os.getenv("SE_CACHE_PATH"):
        return

    fallback_cache = Path.cwd() / ".selenium"
    try:
        fallback_cache.mkdir(parents=True, exist_ok=True)
    except Exception:
        return
    os.environ["SE_CACHE_PATH"] = str(fallback_cache)


def _build_chrome_options(headless: bool, include_profile: bool = True) -> ChromeOptions:
    options = ChromeOptions()

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--disable-gpu")
    # Flags abaixo ajudam mais em Linux/containers; em alguns Windows podem causar instabilidade.
    if sys.platform != "win32":
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=pt-BR")
    options.add_argument("--window-size=1366,768")
    options.add_argument("--disable-blink-features=AutomationControlled")
    # Evita alguns crashes/instabilidades em ambientes Windows.
    if sys.platform == "win32":
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-features=RendererCodeIntegrity")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    if include_profile:
        profile_dir = (os.getenv("SELENIUM_PROFILE_DIR") or "").strip()
        if profile_dir:
            profile_dir = str(Path(profile_dir))
        else:
            profile_dir = str(Path(__file__).resolve().parent.parent / "chrome_profile")
        os.makedirs(profile_dir, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_dir}")

    chrome_binary = _find_chrome_binary()
    if chrome_binary:
        options.binary_location = chrome_binary

    return options


def _build_edge_options(headless: bool, include_profile: bool = True) -> EdgeOptions:
    options = EdgeOptions()

    if headless:
        # Edge tem apresentado instabilidade com --headless=new (DevToolsActivePort).
        # Use headless "legacy" + remote debugging aleatorio para maior compatibilidade.
        options.add_argument("--headless")
        options.add_argument("--remote-debugging-port=0")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")

    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=pt-BR")
    options.add_argument("--window-size=1366,768")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if include_profile:
        profile_dir = (os.getenv("SELENIUM_PROFILE_DIR") or "").strip()
        if profile_dir:
            profile_dir = str(Path(profile_dir))
        else:
            profile_dir = str(Path(__file__).resolve().parent.parent / "edge_profile")
        os.makedirs(profile_dir, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_dir}")

    edge_binary = _find_edge_binary()
    if edge_binary:
        options.binary_location = edge_binary

    return options


def _build_firefox_options(headless: bool, include_profile: bool = True) -> FirefoxOptions:
    options = FirefoxOptions()
    if headless:
        options.add_argument("-headless")
    options.set_preference("intl.accept_languages", "pt-BR")
    options.set_preference("dom.webdriver.enabled", False)

    if include_profile:
        profile_dir = (os.getenv("SELENIUM_PROFILE_DIR") or "").strip()
        if profile_dir:
            profile_dir = str(Path(profile_dir))
        else:
            profile_dir = str(Path(__file__).resolve().parent.parent / "firefox_profile")
        os.makedirs(profile_dir, exist_ok=True)
        options.add_argument("-profile")
        options.add_argument(str(profile_dir))

    firefox_binary = _find_firefox_binary()
    if firefox_binary:
        options.binary_location = firefox_binary
    return options


def _build_remote_options(headless: bool, browser_name: str):
    browser = browser_name.strip().lower()
    if browser == "chrome":
        options = _build_chrome_options(headless=headless, include_profile=False)
    elif browser == "edge":
        # Remoto varia conforme grid/selenoid. Mantemos suporte local prioritario.
        raise ValueError("Edge remoto nao suportado neste ambiente.")
    elif browser == "firefox":
        options = _build_firefox_options(headless=headless, include_profile=False)
    else:
        raise ValueError(f"Browser remoto nao suportado: {browser_name}")

    selenoid_caps = {
        "enableVNC": _env_bool("SELENOID_ENABLE_VNC", True),
        "enableVideo": _env_bool("SELENOID_ENABLE_VIDEO", False),
    }
    browser_version = os.getenv("SELENOID_BROWSER_VERSION", "").strip()
    if browser_version:
        options.set_capability("browserVersion", browser_version)

    options.set_capability("selenoid:options", selenoid_caps)
    return options


def get_driver(
    headless: bool = False,
    remote_url: str | None = None,
    browser_name: str | None = None,
):
    """
    Cria driver Selenium com duas estrategias:
    1) Remoto (Selenoid) se `remote_url` ou `SELENIUM_REMOTE_URL` estiver definido.
    2) Local (ChromeDriver) como fallback.

    Variaveis uteis:
    - SELENIUM_REMOTE_URL
    - SELENIUM_BROWSER (chrome/firefox)
    - SELENOID_ENABLE_VNC (1/0)
    - SELENOID_ENABLE_VIDEO (1/0)
    - SELENOID_BROWSER_VERSION
    - SELENIUM_PAGE_LOAD_TIMEOUT
    """

    effective_remote_url = (remote_url or os.getenv("SELENIUM_REMOTE_URL", "")).strip()
    effective_browser = _normalize_browser_name(browser_name or os.getenv("SELENIUM_BROWSER", "chrome"))
    use_profile = _env_bool("SELENIUM_USE_PROFILE", False)
    _ensure_selenium_cache_path()

    if effective_browser not in SUPPORTED_BROWSERS:
        raise ValueError(f"Browser nao suportado: {effective_browser}")

    if effective_remote_url:
        options = _build_remote_options(headless=headless, browser_name=effective_browser)
        driver = webdriver.Remote(
            command_executor=effective_remote_url,
            options=options,
        )
    else:
        if effective_browser == "chrome":
            options = _build_chrome_options(headless=headless, include_profile=use_profile)
            chrome_driver_path = _resolve_driver_env_path("CHROMEDRIVER_PATH")
            if chrome_driver_path:
                driver = webdriver.Chrome(
                    service=ChromeService(chrome_driver_path),
                    options=options,
                )
            else:
                try:
                    if _webdriver_manager_enabled():
                        driver = webdriver.Chrome(
                            service=ChromeService(ChromeDriverManager().install()),
                            options=options,
                        )
                    else:
                        driver = webdriver.Chrome(options=options)
                except Exception:
                    # Ultimo fallback: PATH/Selenium Manager (evita dependencia hard do webdriver_manager).
                    driver = webdriver.Chrome(options=options)
        elif effective_browser == "edge":
            options = _build_edge_options(headless=headless, include_profile=use_profile)
            edge_driver_path = _resolve_driver_env_path("EDGEDRIVER_PATH")
            if edge_driver_path:
                driver = webdriver.Edge(
                    service=EdgeService(edge_driver_path),
                    options=options,
                )
            else:
                try:
                    if _webdriver_manager_enabled():
                        driver = webdriver.Edge(
                            service=EdgeService(EdgeChromiumDriverManager().install()),
                            options=options,
                        )
                    else:
                        driver = webdriver.Edge(options=options)
                except Exception:
                    driver = webdriver.Edge(options=options)
        elif effective_browser == "firefox":
            options = _build_firefox_options(headless=headless, include_profile=use_profile)
            gecko_driver_path = _resolve_driver_env_path("GECKODRIVER_PATH")
            if gecko_driver_path:
                driver = webdriver.Firefox(
                    service=FirefoxService(gecko_driver_path),
                    options=options,
                )
            else:
                try:
                    driver = webdriver.Firefox(
                        service=FirefoxService(GeckoDriverManager().install()),
                        options=options,
                    )
                except Exception:
                    driver = webdriver.Firefox(options=options)
        else:
            raise ValueError(f"Browser local nao suportado: {effective_browser}")

    # Tentativa leve de reduzir deteccao de automacao em navegadores Chromium.
    if effective_browser in {"chrome", "edge"}:
        try:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                },
            )
        except Exception:
            pass

    page_load_timeout = _env_int(
        "SELENIUM_PAGE_LOAD_TIMEOUT",
        SCRAPER_SETTINGS.selenium_page_load_timeout,
        5,
        300,
    )
    try:
        driver.set_page_load_timeout(page_load_timeout)
    except Exception:
        pass

    return driver
