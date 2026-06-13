import copy
import json
import os
import sys


if getattr(sys, "frozen", False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(application_path, "config.json")
APP_NAME = "Ring Spectrum"
APP_VERSION = "0.5.1"
PRESET_EXPORT_FORMAT = "ring-spectrum-presets"
PRESET_EXPORT_VERSION = 1

PERFORMANCE_MODE_POWER_SAVER = "power_saver"
PERFORMANCE_MODE_BALANCED = "balanced"
PERFORMANCE_MODE_QUALITY = "quality"

COLOR_MODE_SOLID = "solid"
COLOR_MODE_ENDPOINT = "gradient"
COLOR_MODE_VERTICAL = "vertical_gradient"

SP_MODE_NORMAL = "normal"
SP_MODE_BEAT = "beat"

BAR_SMOOTH_KERNEL = (1.0, 4.0, 6.0, 4.0, 1.0)

CUSTOM_FREQUENCY_BANDS = (
    {"id": "sub_bass", "label": "超低频 20-60Hz", "min_hz": 20.0, "max_hz": 60.0},
    {"id": "bass", "label": "Bass 60-160Hz", "min_hz": 60.0, "max_hz": 160.0},
    {"id": "low_mid", "label": "低中频 160-400Hz", "min_hz": 160.0, "max_hz": 400.0},
    {"id": "mid", "label": "中频 400Hz-1kHz", "min_hz": 400.0, "max_hz": 1000.0},
    {"id": "upper_mid", "label": "中高频 1k-2.5kHz", "min_hz": 1000.0, "max_hz": 2500.0},
    {"id": "presence", "label": "存在感 2.5k-5kHz", "min_hz": 2500.0, "max_hz": 5000.0},
    {"id": "high", "label": "高频 5k-10kHz", "min_hz": 5000.0, "max_hz": 10000.0},
    {"id": "air", "label": "空气感 10k-20kHz", "min_hz": 10000.0, "max_hz": 20000.0},
)

CUSTOM_BAND_MIN_VALUE = 0.2
CUSTOM_BAND_MAX_VALUE = 3.0
DEFAULT_CUSTOM_BANDS = {
    band["id"]: {
        "amplitude": 1.0,
        "sensitivity": 1.0,
    }
    for band in CUSTOM_FREQUENCY_BANDS
}

PERFORMANCE_PROFILES = {
    PERFORMANCE_MODE_POWER_SAVER: {
        "label": "省电",
        "fps": 30,
        "root_fade_segments": 24,
        "max_bars": 96,
    },
    PERFORMANCE_MODE_BALANCED: {
        "label": "均衡",
        "fps": 45,
        "root_fade_segments": 40,
        "max_bars": 160,
    },
    PERFORMANCE_MODE_QUALITY: {
        "label": "高质量",
        "fps": 120,
        "root_fade_segments": 64,
        "max_bars": None,
    },
}

DEFAULT_CONFIG = {
    "width": 600,
    "height": 600,
    "x": 100,
    "y": 100,
    "alpha": 100,
    "sensitivity": 5.0,
    "start_color": [0, 255, 255],
    "end_color": [255, 0, 255],
    "bars": 64,
    "decay": 0.8,
    "color_mode": COLOR_MODE_ENDPOINT,
    "sp_mode": SP_MODE_NORMAL,
    "beat_intensity": 1.0,
    "beat_sensitivity": 1.0,
    "beat_expand": 0.22,
    "beat_brightness": 0.55,
    "beat_tail": 0.08,
    "spectrum_style": "ring",
    "spectrum_flip": False,
    "spectrum_rotate_90": False,
    "spectrum_root_fade": False,
    "bar_height": 100.0,
    "bar_length": 100.0,
    "overlay_target": "【默认】桌面底层",
    "performance_mode": PERFORMANCE_MODE_BALANCED,
    "startup_enabled": False,
    "custom_bands_enabled": False,
    "custom_bands": copy.deepcopy(DEFAULT_CUSTOM_BANDS),
}

PRESET_CONFIG_KEYS = tuple(
    key
    for key in DEFAULT_CONFIG.keys()
    if key not in ("performance_mode", "startup_enabled")
)

DEFAULT_CONFIG.update({
    "active_preset": "",
    "presets": {},
})

config = {}


def normalize_color_mode(mode):
    if mode in (COLOR_MODE_SOLID, COLOR_MODE_ENDPOINT, COLOR_MODE_VERTICAL):
        return mode
    return COLOR_MODE_ENDPOINT


def normalize_sp_mode(mode):
    if mode == SP_MODE_BEAT:
        return SP_MODE_BEAT
    return SP_MODE_NORMAL


def normalize_performance_mode(mode):
    if mode in PERFORMANCE_PROFILES:
        return mode
    return PERFORMANCE_MODE_BALANCED


def normalize_preset_name(name):
    if name is None:
        return ""
    return " ".join(str(name).strip().split())


def normalize_bar_count(value):
    try:
        return max(1, int(value))
    except Exception:
        return int(DEFAULT_CONFIG["bars"])


def normalize_color_value(value, fallback):
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        value = fallback
    normalized = []
    for channel in value[:3]:
        try:
            normalized.append(max(0, min(255, int(channel))))
        except Exception:
            normalized.append(0)
    return normalized


def normalize_float_range(value, fallback, minimum, maximum):
    try:
        value = float(value)
    except Exception:
        value = float(fallback)
    return max(float(minimum), min(float(maximum), value))


def normalize_custom_bands(value):
    source = value if isinstance(value, dict) else {}
    normalized = {}
    for band in CUSTOM_FREQUENCY_BANDS:
        band_id = band["id"]
        band_values = source.get(band_id)
        if not isinstance(band_values, dict):
            band_values = {}
        normalized[band_id] = {
            "amplitude": normalize_float_range(
                band_values.get("amplitude"),
                DEFAULT_CUSTOM_BANDS[band_id]["amplitude"],
                CUSTOM_BAND_MIN_VALUE,
                CUSTOM_BAND_MAX_VALUE,
            ),
            "sensitivity": normalize_float_range(
                band_values.get("sensitivity"),
                DEFAULT_CUSTOM_BANDS[band_id]["sensitivity"],
                CUSTOM_BAND_MIN_VALUE,
                CUSTOM_BAND_MAX_VALUE,
            ),
        }
    return normalized


def normalize_config_values(values):
    values.pop("spectrum_balance", None)
    values.pop("ring_center_effect", None)
    values["color_mode"] = normalize_color_mode(values.get("color_mode"))
    values["sp_mode"] = normalize_sp_mode(values.get("sp_mode"))
    values["bars"] = normalize_bar_count(values.get("bars"))
    values["start_color"] = normalize_color_value(values.get("start_color"), DEFAULT_CONFIG["start_color"])
    values["end_color"] = normalize_color_value(values.get("end_color"), DEFAULT_CONFIG["end_color"])
    if "beat_intensity" in values:
        values["beat_intensity"] = normalize_float_range(values.get("beat_intensity"), DEFAULT_CONFIG["beat_intensity"], 0.0, 2.0)
    if "beat_sensitivity" in values:
        values["beat_sensitivity"] = normalize_float_range(values.get("beat_sensitivity"), DEFAULT_CONFIG["beat_sensitivity"], 0.25, 3.0)
    if "beat_expand" in values:
        values["beat_expand"] = normalize_float_range(values.get("beat_expand"), DEFAULT_CONFIG["beat_expand"], 0.0, 1.2)
    if "beat_brightness" in values:
        values["beat_brightness"] = normalize_float_range(values.get("beat_brightness"), DEFAULT_CONFIG["beat_brightness"], 0.0, 1.5)
    if "beat_tail" in values:
        values["beat_tail"] = normalize_float_range(values.get("beat_tail"), DEFAULT_CONFIG["beat_tail"], 0.0, 0.6)
    if "startup_enabled" in values:
        values["startup_enabled"] = bool(values.get("startup_enabled", False))
    if "performance_mode" in values:
        values["performance_mode"] = normalize_performance_mode(values.get("performance_mode"))
    values["custom_bands_enabled"] = bool(values.get("custom_bands_enabled", False))
    values["custom_bands"] = normalize_custom_bands(values.get("custom_bands"))
    return values


def preset_snapshot_from(source, fallback=None):
    source = source if isinstance(source, dict) else {}
    fallback = fallback if isinstance(fallback, dict) else DEFAULT_CONFIG
    snapshot = {}
    for key in PRESET_CONFIG_KEYS:
        if key in source:
            snapshot[key] = copy.deepcopy(source[key])
        else:
            snapshot[key] = copy.deepcopy(fallback[key])
    return normalize_config_values(snapshot)


def normalize_presets():
    presets = config.get("presets")
    if not isinstance(presets, dict):
        presets = {}

    cleaned = {}
    for name, preset in presets.items():
        preset_name = normalize_preset_name(name)
        if preset_name and isinstance(preset, dict):
            cleaned[preset_name] = preset_snapshot_from(preset)

    config["presets"] = cleaned
    active_preset = normalize_preset_name(config.get("active_preset", ""))
    config["active_preset"] = active_preset if active_preset in cleaned else ""


def make_unique_preset_name(base_name):
    base_name = normalize_preset_name(base_name) or "未命名预设"
    presets = config.get("presets", {})
    if base_name not in presets:
        return base_name

    index = 2
    while True:
        candidate = f"{base_name} {index}"
        if candidate not in presets:
            return candidate
        index += 1


def normalize_config():
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = copy.deepcopy(value)
    normalize_config_values(config)
    normalize_presets()


def load_config():
    loaded_config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded_config = json.load(f)
                if not isinstance(loaded_config, dict):
                    loaded_config = {}
        except Exception:
            loaded_config = {}

    config.clear()
    config.update(copy.deepcopy(DEFAULT_CONFIG))
    config.update(loaded_config)
    normalize_config()


def save_config():
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except Exception:
        pass


def read_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def save_current_preset(name):
    name = normalize_preset_name(name)
    if not name:
        return False
    config["presets"][name] = preset_snapshot_from(config)
    config["active_preset"] = name
    normalize_config()
    save_config()
    return True


def delete_preset(name):
    name = normalize_preset_name(name)
    if name not in config.get("presets", {}):
        return False
    del config["presets"][name]
    if config.get("active_preset") == name:
        config["active_preset"] = ""
    save_config()
    return True


def rename_preset(old_name, new_name):
    old_name = normalize_preset_name(old_name)
    new_name = normalize_preset_name(new_name)
    presets = config.get("presets", {})
    if not old_name or old_name not in presets or not new_name or new_name in presets:
        return False

    renamed = {}
    for name, preset in list(presets.items()):
        renamed[new_name if name == old_name else name] = preset
    config["presets"] = renamed
    if config.get("active_preset") == old_name:
        config["active_preset"] = new_name
    normalize_config()
    save_config()
    return True


def duplicate_preset(source_name, new_name=None):
    source_name = normalize_preset_name(source_name)
    presets = config.get("presets", {})
    if source_name not in presets:
        return ""

    if new_name is None:
        new_name = make_unique_preset_name(f"{source_name} 副本")
    else:
        new_name = normalize_preset_name(new_name)
        if not new_name or new_name in presets:
            return ""

    presets[new_name] = preset_snapshot_from(presets[source_name])
    if config.get("active_preset") == source_name:
        config["active_preset"] = new_name
    normalize_config()
    save_config()
    return new_name


def collect_presets_from_export(data):
    if not isinstance(data, dict):
        return {}

    if data.get("format") == PRESET_EXPORT_FORMAT and isinstance(data.get("presets"), dict):
        source_presets = data.get("presets", {})
    elif isinstance(data.get("presets"), dict):
        source_presets = data.get("presets", {})
    elif all(key in data for key in ("width", "height", "start_color", "end_color", "bars")):
        source_presets = {normalize_preset_name(data.get("name", "导入预设")): data}
    else:
        source_presets = data

    imported = {}
    for name, preset in source_presets.items():
        preset_name = normalize_preset_name(name)
        if preset_name and isinstance(preset, dict):
            imported[preset_name] = preset_snapshot_from(preset)
    return imported


def import_presets_from_file(path, replace_existing=False):
    try:
        imported = collect_presets_from_export(read_json_file(path))
    except Exception:
        return 0

    if not imported:
        return 0

    presets = config.setdefault("presets", {})
    active_preset = config.get("active_preset", "")
    for name, preset in imported.items():
        target_name = name if replace_existing else make_unique_preset_name(name)
        presets[target_name] = preset

    if replace_existing and active_preset in imported:
        config["active_preset"] = ""
    normalize_config()
    save_config()
    return len(imported)


def export_presets_to_file(path, names=None):
    presets = config.get("presets", {})
    if names is None:
        selected_names = list(presets.keys())
    else:
        selected_names = [
            normalize_preset_name(name)
            for name in names
            if normalize_preset_name(name) in presets
        ]

    if not selected_names:
        return False

    payload = {
        "format": PRESET_EXPORT_FORMAT,
        "version": PRESET_EXPORT_VERSION,
        "app": APP_NAME,
        "app_version": APP_VERSION,
        "presets": {
            name: preset_snapshot_from(presets[name])
            for name in selected_names
        },
    }
    try:
        write_json_file(path, payload)
    except Exception:
        return False
    return True


def get_performance_profile():
    mode = normalize_performance_mode(config.get("performance_mode"))
    if config.get("performance_mode") != mode:
        config["performance_mode"] = mode
    return PERFORMANCE_PROFILES[mode]


def get_effective_bars():
    bars = normalize_bar_count(config.get("bars"))
    max_bars = get_performance_profile().get("max_bars")
    if max_bars is None:
        return bars
    return min(bars, int(max_bars))


def get_target_fps():
    return int(get_performance_profile()["fps"])


def get_root_fade_segments():
    return int(get_performance_profile()["root_fade_segments"])


def set_performance_mode(mode):
    mode = normalize_performance_mode(mode)
    if config.get("performance_mode") == mode:
        return False
    config["performance_mode"] = mode
    save_config()
    return True
