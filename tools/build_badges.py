"""
Render every badge in the profile README into assets/badges/.

The README does not point at shields.io. It points at files in this repo, and
this script is what produces them. Two reasons for that:

  1. GitHub's camo proxy drops any badge whose URL grows past ~4 KB, which a
     badge with an inlined logo does immediately. AWS and Protocol Buffers both
     rendered as broken images until they became files.
  2. A profile page that fetches 40 images from a third party on every view is
     a third party's uptime problem. github-readme-stats taught that lesson.

Logos come from three places. Most are simple-icons slugs that shields.io
resolves on its own. A few are trademarks shields.io refuses to serve, so their
official SVG lives in assets/icons/brand/ and gets inlined. The concept badges
have no brand at all, so they borrow a Phosphor icon from assets/icons/concept/.

Usage:
    make badges          # or: python tools/build_badges.py
"""

from __future__ import annotations

import base64
import pathlib
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

ROOT = pathlib.Path(__file__).resolve().parent.parent
ICONS = ROOT / "assets/icons"
BADGES = ROOT / "assets/badges"

SHIELDS = "https://img.shields.io/badge"
TIMEOUT = 30

# A badge colour has to survive three readings, and only two numbers are needed
# for them, because contrast is symmetric.
#
# Against the dark page: too dark and the badge dissolves into it, which is how
# five of them once shipped invisible.
#
# Against white, which is read twice over. It is how legible shields.io's white
# label is on top of the badge, and it is also how the badge sits on GitHub's
# light theme, where the page behind it is the same white. The first reading is
# a warning and the second is fatal, so the floor is the lower of the two.
DARK_BG = (0x0D, 0x11, 0x17)
LIGHT_BG = (0xFF, 0xFF, 0xFF)
MIN_PAGE_CONTRAST = 2.0
MIN_LABEL_CONTRAST = 3.0  # a warning, not a failure: see check_colors()


@dataclass(frozen=True)
class Badge:
    """One badge. `icon` is a simple-icons slug unless `local` says otherwise."""

    label: str
    color: str
    icon: str
    local: Optional[str] = None  # relative to assets/icons/, inlined as a data URI

    @property
    def slug(self) -> str:
        return self.label.lower().replace(" ", "-").replace(".", "")


# Concept badges. No brand, no official colour, so both are chosen here: an icon
# that carries the idea and a colour that clears both floors below.
def concept(label: str, color: str) -> Badge:
    slug = label.lower().replace(" ", "-")
    return Badge(label, color, icon="", local=f"concept/{slug}.svg")


GROUPS: dict[str, list[Badge]] = {
    # The thesis line, above the table. Four problems, no vendor.
    "domain": [
        concept("Distributed Systems", "0E7490"),
        concept("High Traffic", "B45309"),
        concept("Scalability", "0F766E"),
        concept("Payments", "1F6FEB"),
    ],
    "architecture": [
        concept("Hexagonal Architecture", "2F6F5E"),
        concept("DDD", "3A5F8A"),
        concept("CQRS", "57518C"),
        concept("Clean Architecture", "6B4A7E"),
        concept("Event-Driven", "9E6A03"),
        concept("Microservices", "2E6B7A"),
        concept("Concurrency", "8B3A62"),
        concept("TDD", "4E7040"),
    ],
    "languages": [
        # Java and OpenJDK are both black in simple-icons. #ED8B00 is the colour
        # Oracle uses for the mark and it survives a dark background.
        Badge("Java", "ED8B00", "openjdk"),
        Badge("PHP", "777BB4", "php"),
        Badge("Go", "00ADD8", "go"),
        Badge("TypeScript", "3178C6", "typescript"),
        Badge("Python", "3776AB", "python"),
        Badge("Ruby", "CC342D", "ruby"),
    ],
    "frameworks": [
        Badge("Spring Boot", "6DB33F", "springboot"),
        Badge("Laravel", "FF2D20", "laravel"),
        # Symfony's mark is black, which sits at 1.11 against the page. #4A4A4A
        # is a deliberate compromise: 2.14, just over the floor, still reads grey.
        Badge("Symfony", "4A4A4A", "symfony"),
        Badge("NestJS", "E0234E", "nestjs"),
        Badge("FastAPI", "009688", "fastapi"),
        Badge("Node.js", "5FA04E", "nodedotjs"),
        Badge("Ruby on Rails", "D30001", "rubyonrails"),
    ],
    "data": [
        Badge("PostgreSQL", "4169E1", "postgresql"),
        Badge("MySQL", "4479A1", "mysql"),
        Badge("Redis", "FF4438", "redis"),
        Badge("MongoDB", "47A248", "mongodb"),
        Badge("Elasticsearch", "005571", "elasticsearch"),
        Badge("Apache Kafka", "4A4A4A", "apachekafka"),  # #231F20 is 1.16, same call as Symfony
        # Protocol Buffers is not in simple-icons under any name.
        Badge("Protobuf", "4285F4", "", local="brand/protobuf.svg"),
    ],
    "cloud": [
        # shields.io will not serve the AWS mark. The badge's own #232F3E navy
        # disappears on a dark page and Smile Orange #FF9900 is too bright to
        # carry white text, so this is the orange the AWS console uses instead.
        Badge("AWS", "EC7211", "", local="brand/aws.svg"),
        Badge("Google Cloud", "4285F4", "googlecloud"),
        Badge("Terraform", "844FBA", "terraform"),
        Badge("Docker", "2496ED", "docker"),
        Badge("Laravel Forge", "FF2D20", "laravel"),
        Badge("GitHub Actions", "2088FF", "githubactions"),
        Badge("Grafana", "F46800", "grafana"),
        Badge("Prometheus", "E6522C", "prometheus"),
        Badge("Sentry", "7553FF", "sentry"),  # brand #362D59 is too dark here
    ],
    "social": [
        Badge("LinkedIn", "0A66C2", "", local="brand/linkedin.svg"),  # trademark, same as AWS
        Badge("Email", "EA4335", "gmail"),
    ],
}


def luminance(rgb: tuple[int, int, int]) -> float:
    """Relative luminance, WCAG 2.1."""
    chan = [v / 255 for v in rgb]
    chan = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in chan]
    return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2]


def contrast(hex_color: str, against: tuple[int, int, int] = DARK_BG) -> float:
    """Contrast ratio between a badge colour and something behind or on top of it."""
    rgb = tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    hi, lo = sorted((luminance(rgb), luminance(against)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def check_colors() -> list[str]:
    """
    Fail on a badge either page would swallow. Only warn on a hard-to-read label.

    Both themes are checked, because a reader's choice of theme is not ours to
    assume and a palette tuned against one of them says nothing about the other.
    Nothing fails against white today, and that is a measurement rather than a
    property: the closest is Java's #ED8B00 at 2.53, so a paler brand colour
    could still walk in and dissolve on the light theme without this.

    The label check stays a warning. Most of what trips it are official brand
    colours, and shipping Go in something other than Go's cyan to win half a
    contrast point would be the wrong trade.
    """
    fatal, warn = [], []
    for badges in GROUPS.values():
        for badge in badges:
            dark = contrast(badge.color, DARK_BG)
            light = contrast(badge.color, LIGHT_BG)
            if dark < MIN_PAGE_CONTRAST:
                fatal.append(f"{badge.label} at #{badge.color} is {dark:.2f} on the dark page")
            if light < MIN_PAGE_CONTRAST:
                fatal.append(f"{badge.label} at #{badge.color} is {light:.2f} on the light page")
            if light < MIN_LABEL_CONTRAST:
                warn.append(f"{badge.label} at #{badge.color} is {light:.2f} under white text")
    for line in warn:
        print(f"  warning: {line}")
    return fatal


def data_uri(relative: str) -> str:
    """Inline a local icon so shields.io can draw a logo it refuses to host."""
    path = ICONS / relative
    if not path.exists():
        sys.exit(f"Icon not found at '{path}'. It is the source for a badge logo.")
    return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode()


def fetch(badge: Badge) -> str:
    """Ask shields.io for one badge and return the SVG."""
    label = urllib.parse.quote(badge.label.replace("-", "--").replace("_", "__"))
    logo = urllib.parse.quote(data_uri(badge.local), safe="") if badge.local else badge.icon
    url = f"{SHIELDS}/-{label}-{badge.color}?logo={logo}&logoColor=FFFFFF"
    request = urllib.request.Request(url, headers={"User-Agent": "sergio-santiago/profile"})
    svg = urllib.request.urlopen(request, timeout=TIMEOUT).read().decode()
    if "base64" not in svg:
        sys.exit(f"shields.io returned '{badge.label}' without its logo. Check the slug.")
    return svg


def main() -> None:
    failures = check_colors()
    for group, badges in GROUPS.items():
        (BADGES / group).mkdir(parents=True, exist_ok=True)
        for badge in badges:
            (BADGES / group / f"{badge.slug}.svg").write_text(fetch(badge))
        print(f"  {group:13} {len(badges):2} badges")

    total = sum(len(b) for b in GROUPS.values())
    print(f"{total} badges written to {BADGES.relative_to(ROOT)}/")

    if failures:
        sys.exit(f"Below the {MIN_PAGE_CONTRAST} contrast floor:\n  " + "\n  ".join(failures))


if __name__ == "__main__":
    main()
