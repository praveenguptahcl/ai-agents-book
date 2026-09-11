"""Shared figure style for the AI-agents book rebuild.

Publication-quality, print-friendly: clean sans-serif, restrained palette,
monospace for code identifiers. Import from render scripts with:

    import sys; sys.path.insert(0, "/home/hatch/workspace/book-rebuild/figures")
    from _style import *
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle
import os

OUTDIR = "/home/hatch/workspace/book-rebuild/figures"

COLORS = {
    "blue":   "#2B6CB0", "blue_lt":   "#D6E7FA",
    "amber":  "#B7791F", "amber_lt":  "#FDF0C8",
    "red":    "#C53030", "red_lt":    "#FADDD8",
    "green":  "#276749", "green_lt":  "#CDEFDB",
    "gray":   "#4A5568", "gray_lt":   "#E8ECF1", "gray_mid": "#A0AEC0",
    "purple": "#6B46C1", "purple_lt": "#E7DCFA",
    "orange": "#C05621", "orange_lt": "#FDEBD3",
    "ink":    "#1A202C", "paper":     "#FFFFFF",
}

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Arial"],
    "axes.unicode_minus": False,
    "text.color": COLORS["ink"],
})

MONO = "monospace"


def new_fig(w=10, h=6):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    return fig, ax


def save(fig, name):
    """Save PNG (200 dpi) and SVG to the figures dir. Returns paths."""
    os.makedirs(OUTDIR, exist_ok=True)
    png = os.path.join(OUTDIR, name + ".png")
    svg = os.path.join(OUTDIR, name + ".svg")
    fig.tight_layout(pad=1.2)
    fig.savefig(png, dpi=200)
    fig.savefig(svg)
    plt.close(fig)
    return png, svg


def box(ax, x, y, w, h, text, face="paper", edge="ink", fs=8.5, mono=False,
        style="round,pad=0.015", lw=1.4, ha="center", va="center", alpha=1.0,
        ls="-"):
    """Draw a labeled box in 0-100 coords. Returns the patch."""
    p = FancyBboxPatch((x, y), w, h, boxstyle=style,
                       facecolor=COLORS.get(face, face),
                       edgecolor=COLORS.get(edge, edge),
                       linewidth=lw, alpha=alpha, linestyle=ls)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha=ha, va=va, fontsize=fs,
            family=MONO if mono else "sans-serif",
            color=COLORS["ink"], wrap=True,
            linespacing=1.35)
    return p


def diamond(ax, cx, cy, w, h, text, face="paper", edge="ink", fs=8, mono=False):
    import matplotlib.patches as mpatches
    d = mpatches.RegularPolygon((cx, cy), 4, radius=1,
                                orientation=0.785398,
                                facecolor=COLORS.get(face, face),
                                edgecolor=COLORS.get(edge, edge), linewidth=1.4)
    # scale to w,h via transform trick: use polygon points instead
    d = plt.Polygon([(cx, cy + h / 2), (cx + w / 2, cy),
                     (cx, cy - h / 2), (cx - w / 2, cy)],
                    closed=True, facecolor=COLORS.get(face, face),
                    edgecolor=COLORS.get(edge, edge), linewidth=1.4)
    ax.add_patch(d)
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fs,
            family=MONO if mono else "sans-serif", color=COLORS["ink"],
            wrap=True, linespacing=1.3)
    return d


def arrow(ax, x1, y1, x2, y2, color="ink", lw=1.6, ls="-", label=None,
          fs=7, rad=0.0, label_pos=0.5):
    a = FancyArrowPatch((x1, y1), (x2, y2),
                        arrowstyle="-|>", mutation_scale=14,
                        color=COLORS.get(color, color), linewidth=lw,
                        linestyle=ls,
                        connectionstyle=f"arc3,rad={rad}",
                        shrinkA=1, shrinkB=3)
    ax.add_patch(a)
    if label:
        mx = x1 + (x2 - x1) * label_pos
        my = y1 + (y2 - y1) * label_pos + 1.2
        ax.text(mx, my, label, ha="center", va="bottom", fontsize=fs,
                family=MONO, color=COLORS.get(color, color),
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none",
                          alpha=0.85))
    return a


def caption(ax, text, y=2.5, fs=8):
    ax.text(50, y, text, ha="center", va="bottom", fontsize=fs,
            style="italic", color=COLORS["gray"], wrap=True,
            bbox=dict(boxstyle="square,pad=0", fc="none", ec="none"))


def title(ax, text, y=96.5, fs=12):
    ax.text(50, y, text, ha="center", va="top", fontsize=fs, weight="bold",
            color=COLORS["ink"])


def stop_mark(ax, x, y, s=3.2, color="red"):
    """Bold red X (defeated path marker)."""
    ax.text(x, y, "\u2715", ha="center", va="center", fontsize=s * 4,
            color=COLORS.get(color, color), weight="bold")
