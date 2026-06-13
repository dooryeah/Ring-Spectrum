import math

import pystray
from PIL import Image, ImageDraw, ImageFilter


def create_image():
    final_size = 64
    scale = 4
    size = final_size * scale
    center = size / 2

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def mix(a, b, t):
        return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

    def polar(radius, degrees):
        radians = math.radians(degrees)
        return (
            center + math.cos(radians) * radius,
            center + math.sin(radians) * radius,
        )

    def rounded_line(points, color, width):
        draw.line(points, fill=color, width=width)
        radius = width / 2
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)

    # Dark glassy base that stays readable on both light and dark taskbars.
    base_bounds = (18, 18, size - 18, size - 18)
    for step in range(80):
        inset = step * 0.9
        t = step / 79
        color = mix((20, 28, 44), (7, 12, 22), t)
        draw.ellipse(
            (
                base_bounds[0] + inset,
                base_bounds[1] + inset,
                base_bounds[2] - inset,
                base_bounds[3] - inset,
            ),
            fill=(*color, 255),
        )

    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((28, 28, size - 28, size - 28), outline=(31, 220, 255, 150), width=10)
    glow_draw.arc((34, 34, size - 34, size - 34), 210, 330, fill=(255, 83, 199, 150), width=12)
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5)))
    draw = ImageDraw.Draw(image)

    # Outer ring spectrum: short radial bars with a deliberate asymmetric rhythm.
    bars = [
        0.36, 0.48, 0.62, 0.44, 0.74, 0.52, 0.90, 0.58,
        0.70, 0.46, 0.84, 0.55, 0.68, 0.42, 0.76, 0.50,
        0.64, 0.40, 0.72, 0.54, 0.88, 0.60, 0.78, 0.46,
        0.66, 0.50, 0.82, 0.56, 0.70, 0.44, 0.58, 0.38,
    ]
    palette = ((41, 231, 255), (119, 255, 153), (255, 83, 199))
    for index, strength in enumerate(bars):
        degrees = -112 + index * (224 / (len(bars) - 1))
        band_t = index / (len(bars) - 1)
        if band_t < 0.55:
            color = mix(palette[0], palette[1], band_t / 0.55)
        else:
            color = mix(palette[1], palette[2], (band_t - 0.55) / 0.45)
        inner_radius = 78 * scale / 4
        outer_radius = (89 + 28 * strength) * scale / 4
        rounded_line(
            (polar(inner_radius, degrees), polar(outer_radius, degrees)),
            (*color, 245),
            7,
        )

    # Simulated acrylic center: translucent core, soft gradient, and clean glass highlights.
    disc_bounds = (76, 76, size - 76, size - 76)
    disc_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(disc_mask).ellipse(disc_bounds, fill=255)
    image = Image.composite(Image.new("RGBA", (size, size), (8, 13, 26, 78)), image, disc_mask)

    acrylic = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    acrylic_draw = ImageDraw.Draw(acrylic)
    for y in range(disc_bounds[1], disc_bounds[3] + 1):
        t = (y - disc_bounds[1]) / (disc_bounds[3] - disc_bounds[1])
        color = mix((218, 248, 255), (40, 66, 105), t)
        alpha = int(128 - 52 * t)
        acrylic_draw.line((disc_bounds[0], y, disc_bounds[2], y), fill=(*color, alpha))

    acrylic_masked = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    acrylic_masked.paste(acrylic, (0, 0), disc_mask)
    image.alpha_composite(acrylic_masked)
    draw = ImageDraw.Draw(image)

    draw.ellipse(disc_bounds, outline=(235, 252, 255, 150), width=4)
    draw.ellipse((86, 86, size - 86, size - 86), outline=(255, 255, 255, 52), width=2)
    draw.arc((83, 82, size - 82, size - 83), 208, 326, fill=(255, 255, 255, 128), width=5)
    draw.arc((93, 93, size - 93, size - 93), 34, 144, fill=(255, 83, 199, 165), width=5)
    draw.arc((93, 93, size - 93, size - 93), 205, 328, fill=(31, 220, 255, 180), width=5)

    waveform = [
        (center - 38, center, center - 28, center),
        (center - 26, center, center - 18, center - 18),
        (center - 18, center - 18, center - 8, center + 20),
        (center - 8, center + 20, center + 4, center - 26),
        (center + 4, center - 26, center + 15, center + 14),
        (center + 15, center + 14, center + 26, center - 8),
        (center + 26, center - 8, center + 38, center - 8),
    ]
    for segment in waveform:
        rounded_line(((segment[0] + 1, segment[1] + 2), (segment[2] + 1, segment[3] + 2)), (2, 6, 16, 150), 11)
    for segment in waveform:
        rounded_line(((segment[0], segment[1]), (segment[2], segment[3])), (240, 255, 255, 245), 7)

    draw.ellipse((63, 50, 91, 78), fill=(255, 255, 255, 48))

    resample_filter = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    return image.resize((final_size, final_size), resample_filter)


def create_tray_icon(
    app_version,
    config,
    on_settings,
    on_quit,
    queue_preset,
    set_performance_mode,
    performance_profiles,
    normalize_performance_mode,
):
    def make_preset_action(name):
        def handler(icon, item):
            queue_preset(name)
        return handler

    def make_preset_checked(name):
        def checked(item):
            return config.get("active_preset") == name
        return checked

    def build_preset_menu_items():
        presets = config.get("presets", {})
        if not presets:
            return (pystray.MenuItem("暂无预设", None, enabled=False),)
        return tuple(
            pystray.MenuItem(
                name,
                make_preset_action(name),
                checked=make_preset_checked(name),
                radio=True,
            )
            for name in presets.keys()
        )

    def make_performance_action(mode):
        def handler(icon, item):
            set_performance_mode(mode)
        return handler

    def make_performance_checked(mode):
        def checked(item):
            return normalize_performance_mode(config.get("performance_mode")) == mode
        return checked

    def build_performance_menu_items():
        return tuple(
            pystray.MenuItem(
                profile["label"],
                make_performance_action(mode),
                checked=make_performance_checked(mode),
                radio=True,
            )
            for mode, profile in performance_profiles.items()
        )

    return pystray.Icon(
        "RingSpectrum",
        create_image(),
        f"环形频谱 v{app_version}",
        menu=pystray.Menu(
            pystray.MenuItem("设置", on_settings),
            pystray.MenuItem("预设", pystray.Menu(build_preset_menu_items)),
            pystray.MenuItem("性能", pystray.Menu(build_performance_menu_items)),
            pystray.MenuItem("退出", on_quit),
        ),
    )
