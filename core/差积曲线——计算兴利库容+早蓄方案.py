import os
import numpy as np
import pandas as pd


def reservoir_calc_monthly(csv_path="例2数据.csv"):
    if not os.path.exists(csv_path):
        print(f"❌ 错误：在当前目录下未找到文件 '{csv_path}'，请确认文件名和路径是否正确！")
        return

    # ==========================================
    # 1. 双编码智能读取 CSV 文件
    # ==========================================
    try:
        df = pd.read_csv(csv_path, encoding='utf-8')
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, encoding='gbk')

    # 清洗列名空格
    df.columns = [c.strip() for c in df.columns]

    # 【核心调整】提取连续的逐月来水量
    # 假设你的 CSV 文件中存储来水量的列名叫作 '来水量' 或 '流量'
    # 如果列名不同，请修改下方方括号内的名字
    if '来水量' in df.columns:
        Q = df['来水量'].values.astype(float)
    elif '流量' in df.columns:
        Q = df['流量'].values.astype(float)
    else:
        # 如果没有明确列名，默认取第一列（排除文本/序号后）或当前的有效数据列
        Q = df.iloc[:, 0].values.astype(float)

    T = len(Q)

    # ==========================================
    # 2. 增加人工输入调节流量（出库流量 q）的窗口
    # ==========================================
    print(f"📊 成功读取数据，共包含 {T} 个月份的来水记录。")
    q_input = float(input(f"💬 【人工输入窗口】请输入电站/水库的目标调节流量 q (m³/s): "))

    # 将输入的标量 q 扩展为与 Q 同长度的数组
    q = np.full_like(Q, q_input, dtype=float)

    # ==========================================
    # 3. 继承并运行你的核心算法逻辑
    # ==========================================
    diff = Q - q
    W = np.cumsum(diff)

    # 寻找全局最大差积点 M 与其后的最小差积点 N
    M = np.argmax(W)
    N = M + np.argmin(W[M:])

    Vx = W[M] - W[N]

    # 初始化状态数组
    V = np.zeros(T)
    Q_early_storage = np.zeros(T)
    Q_spill = np.zeros(T)

    # 执行你原有的【早蓄 + 弃水 + 库容】判断循环
    for i in range(T):
        # 早蓄阶段（M 之前）
        if i <= M:
            V[i] = min(W[i], Vx)
            Q_early_storage[i] = max(Q[i] - q[i], 0)

        # 供水阶段
        elif i <= N:
            V[i] = W[i] - W[N]

        # 供水结束阶段
        else:
            V[i] = max(W[i] - W[N], 0)

        # 弃水判断
        if W[i] > Vx:
            Q_spill[i] = W[i] - Vx

    # ==========================================
    # 4. 整合并打印计算成果表
    # ==========================================
    # 自动生成序号作为时间轴标签
    months_labels = [f"第{i + 1}月" for i in range(T)]

    result = pd.DataFrame({
        "月份": months_labels,
        "来水量Q": Q,
        "调节流量q": q,
        "盈亏差值": diff,
        "W差积": W,
        "库容V": V,
        "早蓄量": Q_early_storage,
        "弃水量": Q_spill
    })

    print("\n" + "=" * 85)
    print(f"📊 连续月流量调节计算成果表 (最大蓄水点: {months_labels[M]}, 放空点: {months_labels[N]})")
    print("=" * 85)
    pd.set_option('display.float_format', lambda x: '%.2f' % x)
    print(result.to_string(index=False))
    print("=" * 85)
    print(f"🏆 在调节流量 q = {q_input:.2f} m³/s 下，计算得出所需设计兴利库容 Vx = {Vx:.2f}")
    print("=" * 85)

    return result, M, N, Vx


if __name__ == "__main__":
    # 自动锁定同目录下的 例2数据.csv
    current_dir = os.path.dirname(os.path.abspath(__file__))
    absolute_csv_path = os.path.join(current_dir, "例2数据.csv")

    reservoir_calc_monthly(absolute_csv_path)