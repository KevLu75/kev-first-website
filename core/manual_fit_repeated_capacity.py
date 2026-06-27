from __future__ import annotations

import csv
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output" / "repeated_capacity_dp_trial"
os.environ.setdefault("MPLCONFIGDIR", str(OUTPUT_DIR / "matplotlib_cache"))

import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import PchipInterpolator, interp1d


INPUT_CSV = OUTPUT_DIR / "dp_trial_all_continuous_summary.csv"
RESULT_CSV = OUTPUT_DIR / "manual_fit_2500h.csv"
TARGET_HOURS = 2500.0

# These points are shown on the interactive chart, but not used by the initial
# reference spline. For 100m, N=30 is also hidden from the final output chart.
EXCLUDED_INITIAL_FIT_CAPACITIES = {
    115.0: {30.0, 40.0},
    108.0: {20.0, 30.0},
    100.0: {30.0},
}
HIDDEN_OUTPUT_CAPACITIES = {
    100.0: {30.0},
}


def read_rows() -> list[dict[str, str]]:
    with INPUT_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def unique_sorted_points(points: list[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    by_x: dict[float, list[float]] = {}
    for x, y in points:
        by_x.setdefault(round(float(x), 6), []).append(float(y))
    xs = np.array(sorted(by_x), dtype=float)
    ys = np.array([sum(by_x[x]) / len(by_x[x]) for x in xs], dtype=float)
    return xs, ys


def find_quadratic_target(coefficients: np.ndarray, max_capacity: float) -> float:
    polynomial = np.array(coefficients, dtype=float)
    polynomial[-1] -= TARGET_HOURS
    roots = np.roots(polynomial)
    real_roots = sorted(
        float(root.real)
        for root in roots
        if abs(root.imag) < 1e-7 and 0.0 <= float(root.real) <= max_capacity
    )
    if not real_roots:
        return 0.0
    return real_roots[0]


def initial_curve(capacities: np.ndarray, hours: np.ndarray, level: float) -> tuple[np.ndarray, np.ndarray, float]:
    excluded = EXCLUDED_INITIAL_FIT_CAPACITIES.get(level, set())
    mask = np.array([float(capacity) not in excluded for capacity in capacities])
    fit_capacities = capacities[mask]
    fit_hours = hours[mask]
    dense_capacity = np.linspace(0.0, float(capacities.max()), 500)
    degree = min(2, len(fit_capacities) - 1)
    coefficients = np.polyfit(fit_capacities, fit_hours, deg=degree)
    return np.polyval(coefficients, dense_capacity), dense_capacity, find_quadratic_target(coefficients, float(capacities.max()))


def build_control_curve(clicked_points: list[tuple[float, float]], fallback_x: np.ndarray, fallback_y: np.ndarray) -> tuple[np.ndarray, np.ndarray, float | str]:
    if len(clicked_points) < 2:
        return fallback_x, fallback_y, interpolate_target(fallback_x, fallback_y)

    xs, ys = unique_sorted_points(clicked_points)
    dense_x = np.linspace(float(xs.min()), float(xs.max()), 500)
    if len(xs) >= 3:
        curve = PchipInterpolator(xs, ys, extrapolate=False)
        dense_y = curve(dense_x)
    else:
        curve = interp1d(xs, ys, kind="linear", bounds_error=False, fill_value=np.nan)
        dense_y = curve(dense_x)

    if float(xs.min()) <= TARGET_HOURS <= float(xs.max()):
        target_n = float(curve(TARGET_HOURS))
    else:
        target_n = ""
    return dense_x, dense_y, target_n


def curve_from_points_or_initial(
    clicked_points: list[tuple[float, float]],
    init_hours: np.ndarray,
    init_capacities: np.ndarray,
    init_target: float,
) -> tuple[np.ndarray, np.ndarray, float | str]:
    if len(clicked_points) < 2:
        return init_hours, init_capacities, init_target
    return build_control_curve(clicked_points, init_hours, init_capacities)


def interpolate_target(xs: np.ndarray, ys: np.ndarray) -> float | str:
    finite = np.isfinite(xs) & np.isfinite(ys)
    xs = xs[finite]
    ys = ys[finite]
    if len(xs) < 2:
        return ""
    order = np.argsort(xs)
    xs = xs[order]
    ys = ys[order]
    if float(xs.min()) <= TARGET_HOURS <= float(xs.max()):
        return float(np.interp(TARGET_HOURS, xs, ys))
    return ""


def save_final_plot(
    level: float,
    capacities: np.ndarray,
    hours: np.ndarray,
    curve_hours: np.ndarray,
    curve_capacities: np.ndarray,
    target_n: float | str,
) -> Path:
    hidden = HIDDEN_OUTPUT_CAPACITIES.get(level, set())
    mask = np.array([float(capacity) not in hidden for capacity in capacities])
    shown_capacities = capacities[mask]
    shown_hours = hours[mask]

    fig, ax = plt.subplots(figsize=(9, 5.4))
    ax.scatter(shown_hours, shown_capacities, color="#111111", s=24, zorder=3)
    ax.plot(curve_hours, curve_capacities, color="#1f77b4", linewidth=2.4)
    ax.axvline(TARGET_HOURS, color="#d62728", linestyle="--", linewidth=1.8)
    if isinstance(target_n, float):
        ax.axhline(target_n, color="#2ca02c", linestyle="--", linewidth=1.6)
        ax.text(TARGET_HOURS, target_n, f"  N={target_n:.2f}", color="#2ca02c", va="bottom")
    ax.set_xlabel("h")
    ax.set_ylabel("N (10k kW)")
    ax.set_title(f"{level:.0f}m manual N-h fit")
    ax.set_ylim(bottom=0.0, top=max(float(np.nanmax(capacities)), float(np.nanmax(curve_capacities))) + 5)
    ax.grid(True, color="#e5e5e5")
    fig.tight_layout()
    output_path = OUTPUT_DIR / f"manual_fit_{level:.0f}m_N_h.svg"
    fig.savefig(output_path)
    plt.close(fig)
    return output_path


def interactive_pick(level: float, capacities: np.ndarray, hours: np.ndarray) -> tuple[np.ndarray, np.ndarray, float | str, int]:
    init_hours, init_capacities, init_target = initial_curve(capacities, hours, level)
    fig, ax = plt.subplots(figsize=(9, 5.4))
    ax.scatter(hours, capacities, color="#111111", s=26, zorder=3)
    (curve_line,) = ax.plot(init_hours, init_capacities, color="#1f77b4", linewidth=2.0)
    (target_line,) = ax.plot([], [], color="#2ca02c", linestyle="--", linewidth=1.6)
    control_scatter = ax.scatter([], [], color="#2ca02c", s=28, zorder=4)
    ax.axvline(TARGET_HOURS, color="#d62728", linestyle="--", linewidth=1.8)
    target_text = ax.text(
        0.03,
        0.95,
        "",
        transform=ax.transAxes,
        va="top",
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#cccccc"},
    )
    ax.set_xlabel("h")
    ax.set_ylabel("N (10k kW)")
    ax.set_title(f"{level:.0f}m: click control points, or press Enter for quadratic fit")
    ax.set_ylim(bottom=0.0, top=max(float(np.nanmax(capacities)), float(np.nanmax(init_capacities))) + 5)
    ax.grid(True, color="#e5e5e5")
    fig.tight_layout()

    picked: list[tuple[float, float]] = []
    done = {"value": False}

    def refresh() -> None:
        curve_hours, curve_capacities, target_n = curve_from_points_or_initial(picked, init_hours, init_capacities, init_target)
        curve_line.set_data(curve_hours, curve_capacities)
        if isinstance(target_n, float):
            target_line.set_data([min(ax.get_xlim()), max(ax.get_xlim())], [target_n, target_n])
            target_text.set_text(f"N(2500h) = {target_n:.2f} 万kW")
        else:
            target_line.set_data([], [])
            target_text.set_text("N(2500h) = 无交点")
        if picked:
            control_scatter.set_offsets(np.array(picked))
        else:
            control_scatter.set_offsets(np.empty((0, 2)))
        fig.canvas.draw_idle()

    def on_click(event) -> None:
        if event.inaxes != ax or event.xdata is None or event.ydata is None:
            return
        picked.append((float(event.xdata), float(event.ydata)))
        refresh()

    def on_key(event) -> None:
        if event.key == "enter":
            done["value"] = True
            plt.close(fig)
        elif event.key in {"backspace", "delete"} and picked:
            picked.pop()
            refresh()

    fig.canvas.mpl_connect("button_press_event", on_click)
    fig.canvas.mpl_connect("key_press_event", on_key)
    refresh()
    print(f"{level:.0f}m: 点击控制点会实时刷新曲线；Backspace 删除上一个点；不点直接 Enter 使用系统二次函数拟合结果。")
    plt.show()

    final_hours, final_capacities, target_n = curve_from_points_or_initial(picked, init_hours, init_capacities, init_target)
    return final_hours, final_capacities, target_n, len(picked)


def main() -> None:
    rows = read_rows()
    result_rows: list[dict[str, float | int | str]] = []
    for level in sorted({float(row["正常蓄水位_m"]) for row in rows}, reverse=True):
        level_rows = [row for row in rows if abs(float(row["正常蓄水位_m"]) - level) < 1e-9]
        capacities = np.array([float(row["重复容量_万kW"]) for row in level_rows], dtype=float)
        hours = np.array([float(row["利用小时数_h"]) for row in level_rows], dtype=float)
        curve_hours, curve_capacities, target_n, point_count = interactive_pick(level, capacities, hours)
        plot_path = save_final_plot(level, capacities, hours, curve_hours, curve_capacities, target_n)
        result_rows.append(
            {
                "正常蓄水位_m": level,
                "2500h对应重复容量_万kW": target_n,
                "控制点数量": point_count,
                "最终图": str(plot_path),
            }
        )

    with RESULT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["正常蓄水位_m", "2500h对应重复容量_万kW", "控制点数量", "最终图"])
        writer.writeheader()
        for row in result_rows:
            writer.writerow({key: round(value, 4) if isinstance(value, float) else value for key, value in row.items()})
    print(f"手动拟合结果已写入: {RESULT_CSV}")


if __name__ == "__main__":
    main()
