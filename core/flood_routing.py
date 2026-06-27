from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"

FLOOD_CSV = DATA_DIR / "设计洪水.csv"
STORAGE_CURVE_CSV = DATA_DIR / "water_level_storage.csv"
DISPATCH_LINES_CSV = OUTPUT_DIR / "dispatch_chart_lines.csv"

SAFE_RELEASE = 20000.0
TIME_STEP_SECONDS = 5 * 3600.0
GRAVITY = 9.81
WIND_FETCH_KM = 15.0
DESIGN_WIND_SPEED = 12.0


@dataclass(frozen=True)
class FloodFacility:
    spillway_count: int
    spillway_crest: float
    spillway_width: float
    spillway_height: float
    outlet_count: int
    outlet_sill: float
    outlet_width: float
    outlet_height: float


@dataclass
class SchemeResult:
    normal_level: float
    flood_limit_level: float
    flood_high_level: float
    flood_high_max_release: float
    design_flood_level: float
    design_max_release: float
    check_flood_level: float
    check_max_release: float
    total_storage_100m_m3: float
    dam_crest_design: float
    dam_crest_check: float
    dam_crest: float


FACILITIES: dict[float, FloodFacility] = {
    120.0: FloodFacility(10, 108.0, 15.0, 12.0, 1, 82.0, 13.0, 8.0),
    115.0: FloodFacility(12, 101.0, 15.0, 14.0, 1, 82.0, 13.0, 8.0),
    108.0: FloodFacility(12, 94.0, 15.0, 14.0, 1, 82.0, 13.0, 8.0),
    100.0: FloodFacility(14, 84.0, 15.0, 16.0, 0, 0.0, 0.0, 0.0),
}

FLOOD_COLUMNS = {
    "5%": "5%",
    "0.1%": "0.10%",
    "0.01%": "0.01%",
}


def read_curve(path: Path) -> tuple[list[float], list[float], list[float]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    levels = [float(row["水位_m"]) for row in rows]
    storages_100m = [float(row["库容_亿m3"]) for row in rows]
    storages_m3 = [value * 100_000_000.0 for value in storages_100m]
    return levels, storages_m3, storages_100m


def interpolate(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1 = xs[i - 1], xs[i]
            y0, y1 = ys[i - 1], ys[i]
            return y0 + (x - x0) * (y1 - y0) / (x1 - x0)
    raise RuntimeError("Interpolation failed")


def read_flood_hydrographs() -> dict[str, list[dict[str, float | str]]]:
    hydrographs = {key: [] for key in FLOOD_COLUMNS}
    with FLOOD_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        column_index = {name: header.index(column) for name, column in FLOOD_COLUMNS.items()}
        last_time_parts = ["", "", ""]
        for step, row in enumerate(reader):
            for index in range(3):
                if row[index] != "":
                    last_time_parts[index] = row[index]
            time_label = "-".join(part for part in last_time_parts if part) or f"{step * 5}h"
            for flood_name, index in column_index.items():
                hydrographs[flood_name].append(
                    {
                        "step": step,
                        "time_h": step * 5.0,
                        "time_label": time_label,
                        "inflow": float(row[index]),
                    }
                )
    return hydrographs


def read_flood_limit_levels() -> dict[float, float]:
    values: dict[float, float] = {}
    with DISPATCH_LINES_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            value = row.get("防洪限制水位_m", "")
            if value == "":
                continue
            level = float(row["正常蓄水位_m"])
            values.setdefault(level, float(value))
    return values


def discharge_capacity(level: float, facility: FloodFacility) -> float:
    spillway_head = max(level - facility.spillway_crest, 0.0)
    spillway_q = 1.77 * facility.spillway_count * facility.spillway_width * spillway_head ** 1.5

    outlet_q = 0.0
    if facility.outlet_count > 0:
        opening = facility.outlet_height
        area = facility.outlet_width * facility.outlet_height
        head_to_center = max(level - (facility.outlet_sill + opening / 2.0), 1e-6)
        coefficient = max(0.0, 0.99 - 0.53 * opening / head_to_center)
        outlet_q = facility.outlet_count * coefficient * area * math.sqrt(2 * GRAVITY * head_to_center)

    return spillway_q + outlet_q


def solve_free_step(
    previous_storage: float,
    previous_inflow: float,
    current_inflow: float,
    previous_release: float,
    facility: FloodFacility,
    levels: list[float],
    storages_m3: list[float],
) -> tuple[float, float, float]:
    storage = previous_storage
    for _ in range(100):
        level = interpolate(storage, storages_m3, levels)
        release = discharge_capacity(level, facility)
        next_storage = previous_storage + (
            (previous_inflow + current_inflow) / 2.0 - (previous_release + release) / 2.0
        ) * TIME_STEP_SECONDS
        next_storage = min(max(next_storage, storages_m3[0]), storages_m3[-1])
        if abs(next_storage - storage) < 1.0:
            storage = next_storage
            break
        storage = next_storage
    level = interpolate(storage, storages_m3, levels)
    release = discharge_capacity(level, facility)
    return storage, level, release


def controlled_step(
    previous_storage: float,
    previous_inflow: float,
    current_inflow: float,
    previous_release: float,
    current_release: float,
    levels: list[float],
    storages_m3: list[float],
) -> tuple[float, float]:
    storage = previous_storage + (
        (previous_inflow + current_inflow) / 2.0 - (previous_release + current_release) / 2.0
    ) * TIME_STEP_SECONDS
    storage = min(max(storage, storages_m3[0]), storages_m3[-1])
    return storage, interpolate(storage, storages_m3, levels)


def route_flood(
    normal_level: float,
    flood_name: str,
    hydrograph: list[dict[str, float | str]],
    flood_limit_level: float,
    levels: list[float],
    storages_m3: list[float],
    flood_high_level: float | None = None,
) -> tuple[list[dict[str, float | str]], float, float]:
    facility = FACILITIES[normal_level]
    flood_limit_storage = interpolate(flood_limit_level, levels, storages_m3)
    flood_limit_capacity = discharge_capacity(flood_limit_level, facility)
    storage = flood_limit_storage
    level = flood_limit_level
    previous_inflow = float(hydrograph[0]["inflow"])
    release = min(previous_inflow, SAFE_RELEASE, flood_limit_capacity)

    rows: list[dict[str, float | str]] = []
    max_level = level
    max_release = release

    for item in hydrograph:
        step = int(item["step"])
        current_inflow = float(item["inflow"])
        mode = ""
        if step == 0:
            mode = "起调"
        else:
            if current_inflow <= min(flood_limit_capacity, SAFE_RELEASE) and storage <= flood_limit_storage + 1e-6:
                storage = flood_limit_storage
                level = flood_limit_level
                release = current_inflow
                mode = "来量小于汛限泄能-来多少泄多少"
            else:
                free_storage, free_level, free_release = solve_free_step(
                    storage,
                    previous_inflow,
                    current_inflow,
                    release,
                    facility,
                    levels,
                    storages_m3,
                )
                if free_release <= SAFE_RELEASE:
                    storage, level, release = free_storage, free_level, free_release
                    mode = "闸门全开自由泄流"
                elif flood_name == "5%":
                    release = SAFE_RELEASE
                    storage, level = controlled_step(
                        storage,
                        previous_inflow,
                        current_inflow,
                        rows[-1]["出库流量_m3s"] if rows else release,
                        release,
                        levels,
                        storages_m3,
                    )
                    mode = "下游防洪标准-控制安全泄量"
                else:
                    if flood_high_level is None:
                        raise RuntimeError("大坝设计/校核洪水调洪需要先给定防洪高水位")
                    controlled_storage, controlled_level = controlled_step(
                        storage,
                        previous_inflow,
                        current_inflow,
                        rows[-1]["出库流量_m3s"] if rows else release,
                        SAFE_RELEASE,
                        levels,
                        storages_m3,
                    )
                    if controlled_level < flood_high_level:
                        storage, level, release = controlled_storage, controlled_level, SAFE_RELEASE
                        mode = "未达防洪高水位-控制安全泄量"
                    else:
                        storage, level, release = free_storage, free_level, free_release
                        mode = "达到防洪高水位后-闸门全开自由泄流"

        max_level = max(max_level, level)
        max_release = max(max_release, release)
        rows.append(
            {
                "正常蓄水位_m": normal_level,
                "洪水标准": flood_name,
                "序号": step,
                "时间_h": float(item["time_h"]),
                "时间标识": item["time_label"],
                "入库流量_m3s": current_inflow,
                "出库流量_m3s": release,
                "库水位_m": level,
                "库容_亿m3": interpolate(storage, storages_m3, [v / 100_000_000.0 for v in storages_m3]),
                "运行方式": mode,
            }
        )
        previous_inflow = current_inflow

    return rows, max_level, max_release


def wind_wave_height(wind_speed: float) -> float:
    return 0.0208 * wind_speed ** 1.25 * WIND_FETCH_KM ** (1.0 / 3.0)


def write_csv(path: Path, rows: list[dict[str, float | str]]) -> None:
    if not rows:
        return
    try:
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            for row in rows:
                writer.writerow({key: round(value, 4) if isinstance(value, float) else value for key, value in row.items()})
    except PermissionError:
        print(f"文件被占用，跳过覆盖: {path}")


def svg_polyline(points: list[tuple[float, float]], color: str, width: float = 2.0, dash: bool = False) -> str:
    if len(points) < 2:
        return ""
    dash_text = ' stroke-dasharray="6 4"' if dash else ""
    point_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polyline points="{point_text}" fill="none" stroke="{color}" stroke-width="{width}"{dash_text}/>'


def plot_routing_charts(process_rows: list[dict[str, float | str]], output_dir: Path) -> list[Path]:
    chart_dir = output_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    flood_order = ["5%", "0.1%", "0.01%"]

    for normal_level in sorted({float(row["正常蓄水位_m"]) for row in process_rows}, reverse=True):
        for flood_name in flood_order:
            rows = [
                row
                for row in process_rows
                if abs(float(row["正常蓄水位_m"]) - normal_level) < 1e-9
                and str(row["洪水标准"]) == flood_name
            ]
            if not rows:
                continue

            times = [float(row["时间_h"]) for row in rows]
            inflows = [float(row["入库流量_m3s"]) for row in rows]
            releases = [float(row["出库流量_m3s"]) for row in rows]
            q_max = max(inflows + releases) * 1.08
            t_min, t_max = min(times), max(times)

            width, height = 980, 560
            left, right, top, bottom = 78, 36, 52, 78
            plot_w = width - left - right
            plot_h = height - top - bottom

            def px(value: float) -> float:
                return left + (value - t_min) / (t_max - t_min) * plot_w

            def py_q(value: float) -> float:
                return top + (q_max - value) / q_max * plot_h

            inflow_points = [(px(t), py_q(q)) for t, q in zip(times, inflows)]
            release_points = [(px(t), py_q(q)) for t, q in zip(times, releases)]

            elements: list[str] = [
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
                '<rect width="100%" height="100%" fill="white"/>',
                f'<text x="{width / 2:.0f}" y="30" text-anchor="middle" font-size="20">{normal_level:.0f}m方案 {flood_name}洪水调洪过程图</text>',
                f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#444"/>',
                f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#444"/>',
            ]

            for tick in range(6):
                q_value = q_max * tick / 5
                y = py_q(q_value)
                elements.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e6e6e6"/>')
                elements.append(f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" font-size="12">{q_value:.0f}</text>')

            for tick in range(0, 7):
                t_value = t_min + (t_max - t_min) * tick / 6
                x = px(t_value)
                elements.append(f'<line x1="{x:.1f}" y1="{height-bottom}" x2="{x:.1f}" y2="{height-bottom+5}" stroke="#444"/>')
                elements.append(f'<text x="{x:.1f}" y="{height-bottom+24}" text-anchor="middle" font-size="12">{t_value:.0f}</text>')

            elements.append(svg_polyline(inflow_points, "#1f77b4", 2.3))
            elements.append(svg_polyline(release_points, "#ff7f0e", 2.3, True))

            elements.append(f'<text x="{left + plot_w / 2:.0f}" y="{height-28}" text-anchor="middle" font-size="14">时间 (h)</text>')
            elements.append(f'<text x="24" y="{height/2:.0f}" transform="rotate(-90 24,{height/2:.0f})" text-anchor="middle" font-size="14">流量 (m3/s)</text>')

            legend_x, legend_y = width - 235, 64
            legend_items = [
                ("入库流量", "#1f77b4", False),
                ("出库流量", "#ff7f0e", True),
            ]
            for index, (name, color, dash) in enumerate(legend_items):
                y = legend_y + index * 24
                elements.append(svg_polyline([(legend_x, y), (legend_x + 36, y)], color, 2.3, dash))
                elements.append(f'<text x="{legend_x+45}" y="{y+4}" font-size="13">{name}</text>')

            elements.append("</svg>")
            safe_flood_name = flood_name.replace("%", "pct").replace(".", "_")
            path = chart_dir / f"flood_routing_{normal_level:.0f}m_{safe_flood_name}.svg"
            path.write_text("\n".join(elements), encoding="utf-8")
            paths.append(path)

    return paths


def plot_discharge_capacity_charts(capacity_rows: list[dict[str, float | str]], output_dir: Path) -> list[Path]:
    chart_dir = output_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    grouped: dict[float, list[dict[str, float | str]]] = {}
    for row in capacity_rows:
        grouped.setdefault(float(row["正常蓄水位_m"]), []).append(row)

    def make_chart(
        rows_by_level: dict[float, list[dict[str, float | str]]],
        title: str,
        path: Path,
    ) -> Path:
        colors = {
            120.0: "#1f77b4",
            115.0: "#ff7f0e",
            108.0: "#2ca02c",
            100.0: "#9467bd",
        }
        all_levels = [float(row["水位_m"]) for rows in rows_by_level.values() for row in rows]
        all_capacities = [float(row["泄流能力_m3s"]) for rows in rows_by_level.values() for row in rows]
        x_min = math.floor(min(all_levels) / 5.0) * 5.0
        x_max = math.ceil(max(all_levels) / 5.0) * 5.0
        y_max = max(all_capacities) * 1.08

        width, height = 980, 560
        left, right, top, bottom = 82, 160, 52, 78
        plot_w = width - left - right
        plot_h = height - top - bottom

        def px(value: float) -> float:
            return left + (value - x_min) / (x_max - x_min) * plot_w

        def py(value: float) -> float:
            return top + (y_max - value) / y_max * plot_h

        elements: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="white"/>',
            f'<text x="{width / 2:.0f}" y="30" text-anchor="middle" font-size="20">{title}</text>',
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#444"/>',
            f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#444"/>',
        ]

        for tick in range(6):
            y_value = y_max * tick / 5
            y = py(y_value)
            elements.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e6e6e6"/>')
            elements.append(f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" font-size="12">{y_value:.0f}</text>')

            x_value = x_min + (x_max - x_min) * tick / 5
            x = px(x_value)
            elements.append(f'<line x1="{x:.1f}" y1="{height-bottom}" x2="{x:.1f}" y2="{height-bottom+5}" stroke="#444"/>')
            elements.append(f'<text x="{x:.1f}" y="{height-bottom+24}" text-anchor="middle" font-size="12">{x_value:.0f}</text>')

        legend_x, legend_y = width - right + 32, 72
        for index, normal_level in enumerate(sorted(rows_by_level, reverse=True)):
            rows = sorted(rows_by_level[normal_level], key=lambda row: float(row["水位_m"]))
            points = [(px(float(row["水位_m"])), py(float(row["泄流能力_m3s"]))) for row in rows]
            color = colors.get(normal_level, "#333333")
            elements.append(svg_polyline(points, color, 2.4))
            y = legend_y + index * 24
            elements.append(svg_polyline([(legend_x, y), (legend_x + 34, y)], color, 2.4))
            elements.append(f'<text x="{legend_x+42}" y="{y+4}" font-size="13">{normal_level:.0f}m方案</text>')

        elements.append(f'<text x="{left + plot_w / 2:.0f}" y="{height-28}" text-anchor="middle" font-size="14">水位 (m)</text>')
        elements.append(f'<text x="24" y="{height/2:.0f}" transform="rotate(-90 24,{height/2:.0f})" text-anchor="middle" font-size="14">泄流能力 (m3/s)</text>')
        elements.append("</svg>")
        path.write_text("\n".join(elements), encoding="utf-8")
        return path

    for normal_level, rows in sorted(grouped.items(), reverse=True):
        path = chart_dir / f"discharge_capacity_{normal_level:.0f}m.svg"
        paths.append(make_chart({normal_level: rows}, f"{normal_level:.0f}m方案 泄流能力曲线", path))

    combined_path = chart_dir / "discharge_capacity_all_schemes.svg"
    paths.append(make_chart(grouped, "各方案泄流能力曲线对比", combined_path))
    return paths


def main() -> None:
    levels, storages_m3, storages_100m = read_curve(STORAGE_CURVE_CSV)
    hydrographs = read_flood_hydrographs()
    flood_limit_levels = read_flood_limit_levels()

    output_dir = OUTPUT_DIR / "flood_routing"
    output_dir.mkdir(parents=True, exist_ok=True)

    all_process_rows: list[dict[str, float | str]] = []
    summary_rows: list[dict[str, float | str]] = []
    capacity_rows: list[dict[str, float | str]] = []

    design_wave = wind_wave_height(DESIGN_WIND_SPEED)
    check_wave = wind_wave_height(DESIGN_WIND_SPEED * 0.8)

    for normal_level in sorted(FACILITIES, reverse=True):
        facility = FACILITIES[normal_level]
        flood_limit_level = flood_limit_levels[normal_level]

        flood_rows, flood_high_level, flood_high_release = route_flood(
            normal_level,
            "5%",
            hydrographs["5%"],
            flood_limit_level,
            levels,
            storages_m3,
        )
        design_rows, design_level, design_release = route_flood(
            normal_level,
            "0.1%",
            hydrographs["0.1%"],
            flood_limit_level,
            levels,
            storages_m3,
            flood_high_level,
        )
        check_rows, check_level, check_release = route_flood(
            normal_level,
            "0.01%",
            hydrographs["0.01%"],
            flood_limit_level,
            levels,
            storages_m3,
            flood_high_level,
        )
        all_process_rows.extend(flood_rows + design_rows + check_rows)

        total_storage_100m = interpolate(check_level, levels, storages_100m)
        dam_crest_design = design_level + design_wave + 0.7
        dam_crest_check = check_level + check_wave + 0.5
        dam_crest = max(dam_crest_design, dam_crest_check)

        summary_rows.append(
            {
                "正常蓄水位_m": normal_level,
                "防洪限制水位_m": flood_limit_level,
                "防洪高水位_m": flood_high_level,
                "防洪高水位最大泄流量_m3s": flood_high_release,
                "设计洪水位_m": design_level,
                "设计洪水最大泄流量_m3s": design_release,
                "校核洪水位_m": check_level,
                "校核洪水最大泄流量_m3s": check_release,
                "总库容_亿m3": total_storage_100m,
                "设计风浪高_m": design_wave,
                "设计安全超高_m": 0.7,
                "设计工况坝顶高程_m": dam_crest_design,
                "校核风浪高_m": check_wave,
                "校核安全超高_m": 0.5,
                "校核工况坝顶高程_m": dam_crest_check,
                "坝顶高程_m": dam_crest,
            }
        )

        for level in [x / 10.0 for x in range(int(flood_limit_level * 10), int((normal_level + 20) * 10) + 1, 5)]:
            capacity_rows.append(
                {
                    "正常蓄水位_m": normal_level,
                    "水位_m": level,
                    "泄流能力_m3s": discharge_capacity(level, facility),
                }
            )

    write_csv(output_dir / "flood_routing_process.csv", all_process_rows)
    write_csv(output_dir / "flood_routing_summary.csv", summary_rows)
    write_csv(output_dir / "flood_discharge_capacity.csv", capacity_rows)
    chart_paths = plot_routing_charts(all_process_rows, output_dir)
    capacity_chart_paths = plot_discharge_capacity_charts(capacity_rows, output_dir)

    print(f"调洪过程已写入: {output_dir / 'flood_routing_process.csv'}")
    print(f"调洪汇总已写入: {output_dir / 'flood_routing_summary.csv'}")
    print(f"泄流能力曲线已写入: {output_dir / 'flood_discharge_capacity.csv'}")
    for path in chart_paths:
        print(f"调洪过程图已写入: {path}")
    for path in capacity_chart_paths:
        print(f"泄流能力曲线图已写入: {path}")


if __name__ == "__main__":
    main()
