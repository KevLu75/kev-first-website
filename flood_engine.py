from __future__ import annotations

import csv
import math
from pathlib import Path


SAFE_RELEASE = 20000.0
TIME_STEP_SECONDS = 5 * 3600.0
GRAVITY = 9.81
FLOOD_COLUMNS = {"5%": "5%", "0.1%": "0.10%", "0.01%": "0.01%"}


def interpolate(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for index in range(1, len(xs)):
        if x <= xs[index]:
            ratio = (x - xs[index - 1]) / (xs[index] - xs[index - 1])
            return ys[index - 1] + ratio * (ys[index] - ys[index - 1])
    raise RuntimeError("插值失败")


def read_storage_curve(path: Path) -> tuple[list[float], list[float], list[float]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    levels = [float(row["水位_m"]) for row in rows]
    storages_100m = [float(row["库容_亿m3"]) for row in rows]
    return levels, [value * 100_000_000 for value in storages_100m], storages_100m


def read_hydrographs(path: Path) -> dict[str, list[dict]]:
    hydrographs = {name: [] for name in FLOOD_COLUMNS}
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        header = next(reader)
        indexes = {name: header.index(column) for name, column in FLOOD_COLUMNS.items()}
        last_time = ["", "", ""]
        for step, row in enumerate(reader):
            for index in range(3):
                if row[index]:
                    last_time[index] = row[index]
            label = "-".join(part for part in last_time if part) or f"{step * 5}h"
            for name, column_index in indexes.items():
                hydrographs[name].append(
                    {"step": step, "time_h": step * 5.0, "time_label": label, "inflow": float(row[column_index])}
                )
    return hydrographs


def discharge_capacity(level: float, scheme: dict) -> float:
    spillway = scheme["spillway"]
    spillway_head = max(level - float(spillway["crestElevation"]), 0.0)
    spillway_q = 1.77 * int(spillway["holes"]) * float(spillway["orificeWidth"]) * spillway_head**1.5
    outlet = scheme["middleOutlet"]
    outlet_q = 0.0
    if int(outlet["holes"]) > 0:
        opening = float(outlet["orificeHeight"])
        area = float(outlet["orificeWidth"]) * opening
        head = max(level - (float(outlet["sillElevation"]) + opening / 2), 1e-6)
        coefficient = max(0.0, 0.99 - 0.53 * opening / head)
        outlet_q = int(outlet["holes"]) * coefficient * area * math.sqrt(2 * GRAVITY * head)
    return spillway_q + outlet_q


def free_step(previous_storage, previous_inflow, inflow, previous_release, scheme, levels, storages):
    storage = previous_storage
    for _ in range(100):
        level = interpolate(storage, storages, levels)
        release = discharge_capacity(level, scheme)
        next_storage = previous_storage + ((previous_inflow + inflow) / 2 - (previous_release + release) / 2) * TIME_STEP_SECONDS
        next_storage = min(max(next_storage, storages[0]), storages[-1])
        if abs(next_storage - storage) < 1:
            storage = next_storage
            break
        storage = next_storage
    level = interpolate(storage, storages, levels)
    return storage, level, discharge_capacity(level, scheme)


def controlled_step(previous_storage, previous_inflow, inflow, previous_release, release, levels, storages):
    storage = previous_storage + ((previous_inflow + inflow) / 2 - (previous_release + release) / 2) * TIME_STEP_SECONDS
    storage = min(max(storage, storages[0]), storages[-1])
    return storage, interpolate(storage, storages, levels)


def route(level_value, flood_name, hydrograph, flood_limit, scheme, levels, storages, flood_high=None, safe_release=SAFE_RELEASE):
    flood_limit_storage = interpolate(flood_limit, levels, storages)
    flood_limit_capacity = discharge_capacity(flood_limit, scheme)
    storage = flood_limit_storage
    level = flood_limit
    previous_inflow = float(hydrograph[0]["inflow"])
    release = min(previous_inflow, safe_release, flood_limit_capacity)
    rows = []
    max_level, max_release = level, release
    for item in hydrograph:
        step = int(item["step"])
        inflow = float(item["inflow"])
        if step == 0:
            mode = "起调"
        elif inflow <= min(flood_limit_capacity, safe_release) and storage <= flood_limit_storage + 1e-6:
            storage, level, release = flood_limit_storage, flood_limit, inflow
            mode = "来量小于汛限泄能-来多少泄多少"
        else:
            free_storage, free_level, free_release = free_step(
                storage, previous_inflow, inflow, release, scheme, levels, storages
            )
            if free_release <= safe_release:
                storage, level, release = free_storage, free_level, free_release
                mode = "闸门全开自由泄流"
            elif flood_name == "5%":
                previous_release = rows[-1]["出库流量_m3s"] if rows else release
                release = safe_release
                storage, level = controlled_step(storage, previous_inflow, inflow, previous_release, release, levels, storages)
                mode = "下游防洪标准-控制安全泄量"
            else:
                if flood_high is None:
                    raise RuntimeError("设计、校核洪水调洪缺少防洪高水位")
                previous_release = rows[-1]["出库流量_m3s"] if rows else release
                controlled_storage, controlled_level = controlled_step(
                    storage, previous_inflow, inflow, previous_release, safe_release, levels, storages
                )
                if controlled_level < flood_high:
                    storage, level, release = controlled_storage, controlled_level, safe_release
                    mode = "未达防洪高水位-控制安全泄量"
                else:
                    storage, level, release = free_storage, free_level, free_release
                    mode = "达到防洪高水位后-闸门全开自由泄流"
        max_level, max_release = max(max_level, level), max(max_release, release)
        rows.append(
            {
                "正常蓄水位_m": level_value,
                "洪水标准": flood_name,
                "序号": step,
                "时间_h": float(item["time_h"]),
                "时间标识": item["time_label"],
                "入库流量_m3s": inflow,
                "出库流量_m3s": release,
                "库水位_m": level,
                "库容_亿m3": storage / 100_000_000,
                "运行方式": mode,
            }
        )
        previous_inflow = inflow
    return rows, max_level, max_release


def run_flood_routing(scheme: dict, flood_limit: float, storage_path: Path, flood_path: Path, safe_release: float = SAFE_RELEASE) -> tuple[dict, list[dict]]:
    levels, storages, storages_100m = read_storage_curve(storage_path)
    hydrographs = read_hydrographs(flood_path)
    normal_level = float(scheme["normalWaterLevel"])
    flood_rows, flood_high, flood_release = route(
        normal_level, "5%", hydrographs["5%"], flood_limit, scheme, levels, storages, safe_release=safe_release
    )
    design_rows, design_level, design_release = route(
        normal_level, "0.1%", hydrographs["0.1%"], flood_limit, scheme, levels, storages, flood_high, safe_release
    )
    check_rows, check_level, check_release = route(
        normal_level, "0.01%", hydrographs["0.01%"], flood_limit, scheme, levels, storages, flood_high, safe_release
    )
    summary = {
        "正常蓄水位_m": normal_level,
        "防洪限制水位_m": flood_limit,
        "防洪高水位_m": flood_high,
        "防洪高水位最大泄流量_m3s": flood_release,
        "设计洪水位_m": design_level,
        "设计洪水最大泄流量_m3s": design_release,
        "校核洪水位_m": check_level,
        "校核洪水最大泄流量_m3s": check_release,
        "总库容_亿m3": interpolate(check_level, levels, storages_100m),
    }
    return summary, flood_rows + design_rows + check_rows


def dam_crest(summary: dict, wind_speed: float, fetch_km: float) -> dict:
    design_wave = 0.0208 * wind_speed**1.25 * fetch_km ** (1 / 3)
    check_wave = 0.0208 * (wind_speed * 0.8) ** 1.25 * fetch_km ** (1 / 3)
    design_crest = float(summary["设计洪水位_m"]) + design_wave + 0.7
    check_crest = float(summary["校核洪水位_m"]) + check_wave + 0.5
    return {
        **summary,
        "设计风速_m_s": wind_speed,
        "水库最大吹程_km": fetch_km,
        "设计风浪高_m": design_wave,
        "设计安全超高_m": 0.7,
        "设计工况坝顶高程_m": design_crest,
        "校核采用风速_m_s": wind_speed * 0.8,
        "校核风浪高_m": check_wave,
        "校核安全超高_m": 0.5,
        "校核工况坝顶高程_m": check_crest,
        "坝顶高程_m": max(design_crest, check_crest),
    }
