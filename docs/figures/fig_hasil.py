"""README figures for the results section: accusation scores and the benchmark.

skor: every Tardos accusation score divided by its own trial's threshold Z, for innocent
recipients and for coalition members. It replays the random stream of
``tapak.tardos.simulate.run_simulation`` with the settings behind
docs/results/simulate_n100_c3.json (N=100, c=3, eps=1e-6, 1000 trials, seed 2026, all
seven strategies), so the extremes drawn here are the ones reported in that file.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator
from matplotlib.transforms import blended_transform_factory

import style
from tapak.tardos.accuse import scores, threshold
from tapak.tardos.attacks import STRATEGIES
from tapak.tardos.code import random_code
from tapak.tardos.params import TardosParams

N, C, EPS, TRIALS, SEED = 100, 3, 1e-6, 1000, 2026


def ribuan(n: int) -> str:
    """Integer with Indonesian thousands separator: 679000 -> 679.000."""
    return f"{n:,}".replace(",", ".")


def persen(x: float) -> str:
    """Fraction as an Indonesian percentage with one decimal: 0.7198 -> 72,0%."""
    return f"{100 * x:.1f}%".replace(".", ",")


def simulate_scores() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Scores over Z for innocents and members, plus every Z (same stream as run_simulation)."""
    params = TardosParams(c=C, eps=EPS, n_max=N)
    rng = np.random.default_rng(SEED)
    innocent, member, zs = [], [], []
    for _ in range(TRIALS):
        p, x_bits = random_code(params, N, rng)
        x = x_bits.astype(np.float64)
        members = rng.choice(N, size=C, replace=False)
        is_member = np.zeros(N, dtype=bool)
        is_member[members] = True
        z_full = threshold(p, params.eps1)
        for strategy in STRATEGIES.values():
            # No channel noise here, so add_channel_noise would draw nothing from rng.
            y, w = strategy(x_bits[members], rng)
            z = z_full if np.all(w == 1.0) else threshold(p, params.eps1, w)
            ratio = scores(x, y, p, w) / z
            innocent.append(ratio[~is_member])
            member.append(ratio[is_member])
            zs.append(z)
    return np.concatenate(innocent), np.concatenate(member), np.array(zs)


def skor(innocent: np.ndarray, member: np.ndarray) -> None:
    """Histogram of innocent and coalition scores against the threshold (log counts)."""
    edges = np.arange(-0.84, 2.66, 0.02)
    floor = 0.45
    hi_inn, lo_mem = float(innocent.max()), float(member.min())
    w, h = 8.8, 3.45
    left, bottom, top = 0.7 / w, 0.66 / h, 1 - 1.1 / h
    row = top + 0.1 / h  # baseline of the y label and the threshold flag

    for t in style.THEMES:
        fig = plt.figure(figsize=(w, h))
        ax = fig.add_axes((left, bottom, 1 - left - 0.04 / w, top - bottom))
        style.style_axes(ax, t, grid_axis=None)

        for data, color in ((innocent, t.info), (member, t.accent)):
            counts, _ = np.histogram(data, edges)
            # Trim to the occupied bins so the outline does not run along the baseline.
            nz = np.flatnonzero(counts)
            span = slice(nz[0], nz[-1] + 1)
            c = np.where(counts[span] > 0, counts[span], floor).astype(float)
            e = edges[nz[0]:nz[-1] + 2]
            ax.stairs(c, e, baseline=floor, fill=True, color=color, alpha=0.22, lw=0)
            ax.stairs(c, e, baseline=floor, color=color, lw=1.1)

        ax.set_yscale("log")
        ax.set_ylim(floor, 1e7)
        ax.set_xlim(edges[0], edges[-1])
        ax.yaxis.set_major_locator(FixedLocator([1, 100, 10_000]))
        ax.yaxis.set_minor_locator(NullLocator())
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: ribuan(int(v))))
        ax.grid(axis="y", color=t.line, lw=0.6)
        ax.set_axisbelow(True)
        ax.xaxis.set_major_locator(FixedLocator(np.arange(-0.5, 2.51, 0.5)))
        ax.xaxis.set_major_formatter(FuncFormatter(
            lambda v, _: f"{100 * v:.0f}%".replace("-", "\u2212")))
        ax.tick_params(labelsize=11, pad=6)
        ax.set_xlabel("skor tuduhan (persen dari ambang Z)", color=t.muted, fontsize=11,
                      labelpad=8)

        # Threshold: one position for every trial once scores are divided by their Z.
        # It runs from the axes bottom up through the label row, which it shares with
        # the y label.
        data_x = blended_transform_factory(ax.transData, fig.transFigure)
        ax.plot([1, 1], [bottom, row + 0.12 / h], color=t.danger, lw=1.4, zorder=3,
                clip_on=False, transform=data_x)
        flag = fig.text(1.025, row, "ambang Z", color=t.danger, fontsize=12,
                        fontweight="semibold", transform=data_x)
        flag_end = fig.transFigure.inverted().transform(flag.get_window_extent().p1)[0]
        fig.text(flag_end + 0.008, row, "(ditetapkan sebelum skor dihitung)", color=t.muted,
                 fontsize=11)
        fig.text(0, row, "jumlah skor (skala log)", color=t.muted, fontsize=11)

        # Direct labels instead of a legend, each anchored to the extreme it reports so
        # the empty band between them is the margin around Z.
        for x, ha, name, note in (
            (hi_inn, "right", "penerima tak bersalah", f"skor tertinggi {persen(hi_inn)} dari Z"),
            (lo_mem, "left", "anggota koalisi", f"skor terendah {persen(lo_mem)} dari Z"),
        ):
            ax.text(x, 1.5e6, name, color=t.text, fontsize=12, ha=ha)
            ax.annotate(note, (x, 1.5e6), xytext=(0, -17), textcoords="offset points",
                        color=t.muted, fontsize=12, ha=ha)

        fig.text(0, 1 - 0.06 / h, "Simulasi kolusi: tidak ada penerima tak bersalah yang mencapai ambang",
                 color=t.text, fontsize=13, fontweight="semibold", va="top")
        fig.text(0, 1 - 0.33 / h,
                 f"Tingkat kode, tanpa derau kanal. N = {N} penerima, c = {C}, \u03b5 = 10\u207b\u2076, "
                 f"{ribuan(TRIALS)} percobaan \u00d7 {len(STRATEGIES)} strategi serangan",
                 color=t.muted, fontsize=11, va="top")
        style.save(fig, "skor", t)


def main() -> None:
    style.setup_fonts()
    innocent, member, zs = simulate_scores()
    print(f"trials={TRIALS} strategies={len(STRATEGIES)} seed={SEED}")
    # The six full-word strategies share Z with majority; erase gets its own Z.
    z = dict(zip(STRATEGIES, zs.reshape(TRIALS, len(STRATEGIES)).T))
    for name in ("majority", "erase"):
        zn = z[name]
        print(f"Z {name}: mean {zn.mean():.2f}, range {zn.min():.2f}..{zn.max():.2f}")
    print(f"innocent scores {innocent.size}, max/Z {innocent.max():.4f}, "
          f"at or above Z {int(np.count_nonzero(innocent >= 1))}")
    print(f"member scores {member.size}, min/Z {member.min():.4f}, "
          f"below Z {int(np.count_nonzero(member < 1))}")
    skor(innocent, member)

    from _fig_benchmark import benchmark
    benchmark()


if __name__ == "__main__":
    main()
