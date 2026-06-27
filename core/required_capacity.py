from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output"

GUARANTEED_OUTPUT_CSV = OUTPUT_DIR / "guaranteed_output_results.csv"
REQUIRED_CAPACITY_CSV = OUTPUT_DIR / "required_capacity_results.csv"

# Values from the course design instruction, Section 4.
NAVIGATION_BASE_LOAD_10K_KW = 10.0
PEAK_CAPACITY_FACTOR = 3.08
PEAK_CAPACITY_CONSTANT_10K_KW = 7.0
RESERVE_CAPACITY_BY_NORMAL_LEVEL = {
    120.0: 30.0,
    115.0: 25.0,
    108.0: 20.0,
    100.0: 15.0,
}


@dataclass
class RequiredCapacityResult:
    normal_level: float
    dead_level: float
    guaranteed_output_10k_kw: float
    base_work_capacity_10k_kw: float
    peak_guaranteed_output_10k_kw: float
    peak_work_capacity_10k_kw: float
    work_capacity_10k_kw: float
    reserve_capacity_10k_kw: float
    required_capacity_10k_kw: float


def read_guaranteed_output(path: Path) -> list[dict[str, float]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [
            {
                "normal_level": float(row["正常蓄水位_m"]),
                "dead_level": float(row["死水位_m"]),
                "guaranteed_output_10k_kw": float(row["保证出力_万kW"]),
            }
            for row in csv.DictReader(f)
        ]


def calculate_required_capacity(row: dict[str, float]) -> RequiredCapacityResult:
    normal_level = row["normal_level"]
    guaranteed_output = row["guaranteed_output_10k_kw"]
    reserve_capacity = RESERVE_CAPACITY_BY_NORMAL_LEVEL[normal_level]

    peak_guaranteed_output = guaranteed_output - NAVIGATION_BASE_LOAD_10K_KW
    peak_work_capacity = PEAK_CAPACITY_FACTOR * peak_guaranteed_output + PEAK_CAPACITY_CONSTANT_10K_KW
    work_capacity = peak_work_capacity + NAVIGATION_BASE_LOAD_10K_KW
    required_capacity = work_capacity + reserve_capacity

    return RequiredCapacityResult(
        normal_level=normal_level,
        dead_level=row["dead_level"],
        guaranteed_output_10k_kw=guaranteed_output,
        base_work_capacity_10k_kw=NAVIGATION_BASE_LOAD_10K_KW,
        peak_guaranteed_output_10k_kw=peak_guaranteed_output,
        peak_work_capacity_10k_kw=peak_work_capacity,
        work_capacity_10k_kw=work_capacity,
        reserve_capacity_10k_kw=reserve_capacity,
        required_capacity_10k_kw=required_capacity,
    )


def write_results(results: list[RequiredCapacityResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "正常蓄水位_m",
                "死水位_m",
                "保证出力_万kW",
                "航运基荷工作容量_万kW",
                "峰荷保证出力_万kW",
                "峰荷工作容量_万kW",
                "工作容量_万kW",
                "备用容量_万kW",
                "必须容量_万kW",
            ]
        )
        for row in results:
            writer.writerow(
                [
                    row.normal_level,
                    round(row.dead_level, 2),
                    round(row.guaranteed_output_10k_kw, 4),
                    round(row.base_work_capacity_10k_kw, 4),
                    round(row.peak_guaranteed_output_10k_kw, 4),
                    round(row.peak_work_capacity_10k_kw, 4),
                    round(row.work_capacity_10k_kw, 4),
                    round(row.reserve_capacity_10k_kw, 4),
                    round(row.required_capacity_10k_kw, 4),
                ]
            )


def main() -> None:
    rows = read_guaranteed_output(GUARANTEED_OUTPUT_CSV)
    results = [calculate_required_capacity(row) for row in rows]
    write_results(results, REQUIRED_CAPACITY_CSV)

    print(f"必须容量结果已写入: {REQUIRED_CAPACITY_CSV}")
    for row in results:
        print(
            f"Z_normal={row.normal_level:.0f} m, "
            f"N_work={row.work_capacity_10k_kw:.4f} 万kW, "
            f"N_required={row.required_capacity_10k_kw:.4f} 万kW"
        )


if __name__ == "__main__":
    main()
