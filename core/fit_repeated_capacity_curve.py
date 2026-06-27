from __future__ import annotations

import csv
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output" / "repeated_capacity_dp_trial"
INPUT_CSV = OUTPUT_DIR / "dp_trial_all_continuous_summary.csv"
OUTPUT_CSV = OUTPUT_DIR / "dp_trial_fit_2500h.csv"

TARGET_HOURS = 2500.0
EXCLUDED_FIT_CAPACITIES = {
    115.0: {30.0, 40.0},
    108.0: {20.0, 30.0},
    100.0: {30.0},
}
EXCLUDED_PLOT_CAPACITIES = {
    100.0: {30.0},
}


def read_rows() -> list[dict[str, str]]:
    with INPUT_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def find_crossing(capacities: np.ndarray, fitted_hours: np.ndarray) -> float | str:
    values = fitted_hours - TARGET_HOURS
    for i in range(1, len(capacities)):
        if abs(values[i]) < 1e-9:
            return float(capacities[i])
        if values[i - 1] * values[i] < 0:
            x0, x1 = capacities[i - 1], capacities[i]
            y0, y1 = values[i - 1], values[i]
            return float(x0 + (0 - y0) * (x1 - x0) / (y1 - y0))
    return ""


def find_extended_crossing(coefficients: np.ndarray, max_capacity: float) -> float | str:
    polynomial = np.array(coefficients, dtype=float)
    polynomial[-1] -= TARGET_HOURS
    roots = np.roots(polynomial)
    real_roots = sorted(
        float(root.real)
        for root in roots
        if abs(root.imag) < 1e-7 and 0.0 <= float(root.real) <= max_capacity
    )
    if not real_roots:
        return ""
    return real_roots[0]


def svg_polyline(points: list[tuple[float, float]], color: str, width: float = 2.0, dash: bool = False) -> str:
    if len(points) < 2:
        return ""
    dash_text = ' stroke-dasharray="6 4"' if dash else ""
    point_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polyline points="{point_text}" fill="none" stroke="{color}" stroke-width="{width}"{dash_text}/>'


def plot_fit(
    level: float,
    capacities: np.ndarray,
    hours: np.ndarray,
    fit_capacities: np.ndarray,
    fit_hours: np.ndarray,
    plot_capacities: np.ndarray,
    plot_hours: np.ndarray,
    dense_capacities: np.ndarray,
    fitted_hours: np.ndarray,
    selected_capacity: float | str,
) -> Path:
    output_path = OUTPUT_DIR / f"dp_trial_{level:.0f}m_N_h_fit.svg"
    x_values = list(fitted_hours) + list(plot_hours) + [TARGET_HOURS]
    y_values = list(dense_capacities) + list(plot_capacities)
    x_min, x_max = min(x_values) - 150, max(x_values) + 150
    y_min, y_max = 0.0, max(y_values) + 5

    width, height = 900, 540
    left, right, top, bottom = 85, 35, 50, 75
    plot_w, plot_h = width - left - right, height - top - bottom

    def px(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w

    def py(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_h

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width / 2:.0f}" y="28" text-anchor="middle" font-size="20">{level:.0f}m N-h 二次函数最小二乘拟合</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#444"/>',
        f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#444"/>',
    ]
    for tick in range(6):
        value = x_min + (x_max - x_min) * tick / 5
        x = px(value)
        elements.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height-bottom}" stroke="#e6e6e6"/>')
        elements.append(f'<text x="{x:.1f}" y="{height-bottom+24}" text-anchor="middle" font-size="12">{value:.0f}</text>')
    for tick in range(6):
        value = y_min + (y_max - y_min) * tick / 5
        y = py(value)
        elements.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e6e6e6"/>')
        elements.append(f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" font-size="12">{value:.0f}</text>')

    target_y = py(TARGET_HOURS)
    target_x = px(TARGET_HOURS)
    elements.append(f'<line x1="{target_x:.1f}" y1="{top}" x2="{target_x:.1f}" y2="{height-bottom}" stroke="#d62728" stroke-width="2" stroke-dasharray="6 4"/>')
    elements.append(f'<text x="{target_x+6:.1f}" y="{top+18}" font-size="12" fill="#d62728">2500h</text>')

    raw_points = [(px(float(hour)), py(float(capacity))) for capacity, hour in zip(plot_capacities, plot_hours)]
    included_points = [(px(float(hour)), py(float(capacity))) for capacity, hour in zip(fit_capacities, fit_hours)]
    fit_points = [(px(float(hour)), py(float(capacity))) for capacity, hour in zip(dense_capacities, fitted_hours)]
    elements.append(svg_polyline(raw_points, "#bbbbbb", 1.3, True))
    elements.append(svg_polyline(fit_points, "#1f77b4", 2.6))
    for x, y in raw_points:
        elements.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#111111"/>')

    if isinstance(selected_capacity, float):
        y = py(selected_capacity)
        elements.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#2ca02c" stroke-width="2" stroke-dasharray="5 4"/>')
        elements.append(f'<text x="{left+8}" y="{y-6:.1f}" font-size="12" fill="#2ca02c">N={selected_capacity:.2f}</text>')

    elements.append(f'<text x="{left + plot_w / 2:.0f}" y="{height-25}" text-anchor="middle" font-size="14">利用小时数 h</text>')
    elements.append(f'<text x="24" y="{height/2:.0f}" transform="rotate(-90 24,{height/2:.0f})" text-anchor="middle" font-size="14">重复容量 N (万kW)</text>')
    elements.append("</svg>")
    output_path.write_text("\n".join(elements), encoding="utf-8")
    return output_path


def main() -> None:
    rows = read_rows()
    levels = sorted({float(row["正常蓄水位_m"]) for row in rows}, reverse=True)
    output_rows: list[dict[str, float | str]] = []

    for level in levels:
        level_rows = [row for row in rows if abs(float(row["正常蓄水位_m"]) - level) < 1e-9]
        capacities = np.array([float(row["重复容量_万kW"]) for row in level_rows])
        hours = np.array([float(row["利用小时数_h"]) for row in level_rows])
        excluded = EXCLUDED_FIT_CAPACITIES.get(level, set())
        plot_excluded = EXCLUDED_PLOT_CAPACITIES.get(level, set())
        fit_mask = np.array([float(capacity) not in excluded for capacity in capacities])
        plot_mask = np.array([float(capacity) not in plot_excluded for capacity in capacities])
        fit_capacities = capacities[fit_mask]
        fit_hours = hours[fit_mask]
        plot_capacities = capacities[plot_mask]
        plot_hours = hours[plot_mask]
        dense_capacities = np.linspace(0.0, float(capacities.max()), 500)

        coefficients = np.polyfit(fit_capacities, fit_hours, deg=2)
        fitted_hours = np.polyval(coefficients, dense_capacities)

        crossing = find_extended_crossing(coefficients, float(capacities.max()))
        if crossing == "":
            selected_capacity: float | str = 0.0
            note = "二次拟合曲线延伸后在N>=0范围内未与2500h有效相交，按经济判据取0"
        else:
            selected_capacity = crossing
            note = "由二次最小二乘曲线延伸至2500h读取"

        plot_path = plot_fit(
            level,
            capacities,
            hours,
            fit_capacities,
            fit_hours,
            plot_capacities,
            plot_hours,
            dense_capacities,
            fitted_hours,
            selected_capacity,
        )
        output_rows.append(
            {
                "正常蓄水位_m": level,
                "拟合方法": "二次函数最小二乘",
                "2500h对应重复容量_万kW": selected_capacity,
                "最大拟合用点利用小时数_h": float(fit_hours.max()),
                "备注": note,
                "拟合图": str(plot_path),
            }
        )

    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "正常蓄水位_m",
                "拟合方法",
                "2500h对应重复容量_万kW",
                "最大拟合用点利用小时数_h",
                "备注",
                "拟合图",
            ],
        )
        writer.writeheader()
        for row in output_rows:
            writer.writerow({key: round(value, 4) if isinstance(value, float) else value for key, value in row.items()})

    print(f"拟合结果已写入: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
