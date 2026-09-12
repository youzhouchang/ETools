"""Target catalog: curated, built-in, custom, and CMSIS-Pack helpers."""

from __future__ import annotations

from functools import lru_cache

from etools.config import get_config, save_config

# Curated shortlist shown first (multi-vendor). UI still lists every built-in target.
CURATED_TARGETS: list[tuple[str, str]] = [
    ("cortex_m", "Generic Cortex-M"),
    # ST
    ("stm32f051", "ST · STM32F051"),
    ("stm32f103rc", "ST · STM32F103RC"),
    ("stm32f429xi", "ST · STM32F429XI"),
    ("stm32f767zi", "ST · STM32F767ZI"),
    ("stm32h743xx", "ST · STM32H743XX"),
    ("stm32l432kc", "ST · STM32L432KC"),
    # Nordic
    ("nrf51", "Nordic · nRF51"),
    ("nrf52832", "Nordic · nRF52832"),
    ("nrf52840", "Nordic · nRF52840"),
    # Raspberry Pi
    ("rp2040", "RPi · RP2040"),
    ("rp2350", "RPi · RP2350"),
    # NXP
    ("lpc1768", "NXP · LPC1768"),
    ("lpc55s69", "NXP · LPC55S69"),
    ("k22f", "NXP · K22F"),
    # GigaDevice / HDSC / Maxim / TI / Cypress
    ("gd32f103", "GD · GD32F103"),
    ("hc32f460", "HDSC · HC32F460"),
    ("hc32l136", "HDSC · HC32L136"),
    ("max32625", "Maxim · MAX32625"),
    ("cc3220sf", "TI · CC3220SF"),
    ("cy8c6xx7", "Cypress · PSoC6 CY8C6xx7"),
]

VENDOR_ORDER = [
    "ST",
    "Nordic",
    "RPi",
    "NXP",
    "GigaDevice",
    "WCH",
    "Artery",
    "MindMotion",
    "HDSC",
    "Air",
    "Maxim",
    "TI",
    "Cypress",
    "Microchip",
    "SiliconLabs",
    "FMD",
    "Custom",
    "Other",
]


def vendor_of(name: str) -> str:
    n = (name or "").lower()
    if n.startswith("stm32"):
        return "ST"
    if n.startswith(("nrf", "nrf91")):
        return "Nordic"
    if n.startswith("rp2") or n.startswith("raspi"):
        return "RPi"
    if n.startswith("hc32"):
        return "HDSC"
    if n.startswith("air"):
        return "Air"
    if n.startswith("lpc") or n.startswith(("k20", "k22", "k32", "mimx", "imx")):
        return "NXP"
    if n.startswith("max326"):
        return "Maxim"
    if n.startswith("sam"):
        return "Microchip"
    if n.startswith("at32"):
        return "Artery"
    if n.startswith("ch32"):
        return "WCH"
    if n.startswith("gd32"):
        return "GigaDevice"
    if n.startswith("mm32"):
        return "MindMotion"
    if n.startswith(("cy8", "cypress")):
        return "Cypress"
    if n.startswith("cc"):
        return "TI"
    if n.startswith("efm"):
        return "SiliconLabs"
    if n.startswith("fm"):
        return "FMD"
    return "Other"


def custom_targets() -> list[dict]:
    raw = get_config().custom_targets or []
    out = []
    for item in raw:
        if isinstance(item, dict) and item.get("name"):
            out.append(
                {
                    "name": str(item["name"]),
                    "label": str(item.get("label") or item["name"]),
                    "vendor": str(item.get("vendor") or "Custom"),
                }
            )
    return out


def add_custom_target(name: str, label: str = "", vendor: str = "Custom") -> bool:
    name = (name or "").strip()
    if not name:
        return False
    cfg = get_config()
    items = [t for t in (cfg.custom_targets or []) if isinstance(t, dict)]
    if any(str(t.get("name", "")).lower() == name.lower() for t in items):
        return False
    items.append(
        {
            "name": name,
            "label": (label or name).strip(),
            "vendor": (vendor or "Custom").strip() or "Custom",
        }
    )
    cfg.custom_targets = items
    save_config()
    invalidate_target_cache()
    return True


def remove_custom_target(name: str) -> bool:
    cfg = get_config()
    items = [t for t in (cfg.custom_targets or []) if isinstance(t, dict)]
    new = [t for t in items if str(t.get("name", "")) != name]
    if len(new) == len(items):
        return False
    cfg.custom_targets = new
    save_config()
    invalidate_target_cache()
    return True


def invalidate_target_cache() -> None:
    list_target_choices.cache_clear()
    group_targets_by_vendor.cache_clear()


def builtin_target_names() -> list[str]:
    try:
        from pyocd.target.builtin import BUILTIN_TARGETS

        return sorted(BUILTIN_TARGETS.keys())
    except Exception:
        return []


def hidden_targets() -> set[str]:
    raw = get_config().hidden_targets or []
    return {str(x) for x in raw if x}


def hide_target(name: str) -> bool:
    """Hide a built-in (or curated) target from the catalog."""
    name = (name or "").strip()
    if not name:
        return False
    cfg = get_config()
    hidden = [str(x) for x in (cfg.hidden_targets or [])]
    if name in hidden:
        return False
    hidden.append(name)
    cfg.hidden_targets = hidden
    save_config()
    invalidate_target_cache()
    return True


def unhide_target(name: str) -> bool:
    cfg = get_config()
    hidden = [str(x) for x in (cfg.hidden_targets or []) if str(x) != name]
    if len(hidden) == len(cfg.hidden_targets or []):
        return False
    cfg.hidden_targets = hidden
    save_config()
    invalidate_target_cache()
    return True


def unhide_all_targets() -> None:
    cfg = get_config()
    cfg.hidden_targets = []
    cfg.hidden_vendors = []
    save_config()
    invalidate_target_cache()


def hidden_vendors() -> set[str]:
    raw = get_config().hidden_vendors or []
    return {str(x) for x in raw if x}


def hide_vendor(vendor: str) -> bool:
    """Hide every target of a vendor from the catalog."""
    vendor = (vendor or "").strip()
    if not vendor or vendor in ("全部", "All", "Generic"):
        return False
    cfg = get_config()
    vendors = [str(x) for x in (cfg.hidden_vendors or [])]
    if vendor in vendors:
        return False
    vendors.append(vendor)
    cfg.hidden_vendors = vendors
    save_config()
    invalidate_target_cache()
    return True


def unhide_vendor(vendor: str) -> bool:
    cfg = get_config()
    vendors = [str(x) for x in (cfg.hidden_vendors or []) if str(x) != vendor]
    if len(vendors) == len(cfg.hidden_vendors or []):
        return False
    cfg.hidden_vendors = vendors
    save_config()
    invalidate_target_cache()
    return True


def vendor_of_label(label: str, name: str) -> str:
    if name == "cortex_m":
        return "Generic"
    if " · " in label:
        return label.split(" · ", 1)[0]
    return vendor_of(name)


@lru_cache(maxsize=1)
def list_target_choices() -> list[tuple[str, str]]:
    """Return (target_override, display) — custom + curated first, then built-ins."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    hidden = hidden_targets()
    hid_v = hidden_vendors()

    def add(name: str, label: str) -> None:
        if not name or name in seen or name in hidden:
            return
        if vendor_of_label(label, name) in hid_v:
            return
        seen.add(name)
        out.append((name, label))

    for t in custom_targets():
        add(t["name"], f"{t['vendor']} · {t['label']}")
    for name, label in CURATED_TARGETS:
        add(name, label)
    for name in builtin_target_names():
        add(name, f"{vendor_of(name)} · {name}")
    return out


@lru_cache(maxsize=1)
def group_targets_by_vendor() -> dict[str, list[tuple[str, str]]]:
    """Group all known targets by vendor for the device manager UI."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for name, label in list_target_choices():
        if name == "cortex_m":
            vendor = "Generic"
        elif label.startswith("Custom ·"):
            vendor = "Custom"
        else:
            vendor = vendor_of(name)
            # prefer label vendor prefix if present
            if " · " in label:
                vendor = label.split(" · ", 1)[0]
        groups.setdefault(vendor, []).append((name, label))
    return groups


def _pyocd_cmd() -> list[str]:
    """Prefer `python -m pyocd` so frozen/venv installs still work."""
    import shutil
    import sys

    exe = shutil.which("pyocd")
    if exe:
        return [exe]
    return [sys.executable, "-m", "pyocd"]


def list_installed_packs() -> list[str]:
    """Return lines from `pyocd pack list` (empty if unavailable)."""
    import subprocess

    try:
        r = subprocess.run(
            _pyocd_cmd() + ["pack", "list"],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = (r.stdout or "") + (r.stderr or "")
        lines = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
        return lines
    except Exception:
        return []


def install_pack(pack_id: str) -> tuple[bool, str]:
    """Install CMSIS pack, e.g. `GigaDevice::GD32F103C8`."""
    import subprocess

    pack_id = (pack_id or "").strip()
    if not pack_id:
        return False, "请输入 Pack ID，例如 Vendor::Part"
    try:
        r = subprocess.run(
            _pyocd_cmd() + ["pack", "install", pack_id],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        msg = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, msg.strip()[-2000:] or (
            "完成" if r.returncode == 0 else f"退出码 {r.returncode}"
        )
    except Exception as exc:
        return False, str(exc)


# Back-compat alias
KNOWN_TARGETS = CURATED_TARGETS
