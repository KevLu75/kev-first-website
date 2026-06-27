import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False


def honest_two_curve_tangent(csv_path, V, Q0=None):
    df = pd.read_csv(csv_path)
    Q = df["流量"].values.astype(float) if "流量" in df.columns else df.iloc[:, 0].values.astype(float)
    T = len(Q)

    if Q0 is None:
        Q0 = np.mean(Q)

    # 1. 规规矩矩定义两个独立的边界数组
    W_upper = np.cumsum(Q - Q0)
    W_lower = W_upper - V
    t_all = np.arange(T)

    valid_tangents = []
    eps = 1e-5

    # 2. 挨个遍历两条线：i 遍历下边界，j 遍历上边界
    for i in range(T):
        for j in range(T):
            if i >= j:
                continue  # 必须先与下边界相切，再与后面的上边界相切

            # 跨越下边界 i 和上边界 j 的直线斜率
            k = (W_upper[j] - W_lower[i]) / (j - i)

            # --- 检查 1：整个跨线线段在它们各自的区间内是否穿墙 ---
            t_start, t_end = min(i, j), max(i, j)
            t_segment = np.arange(t_start, t_end + 1)
            # 直线在这一段的纵坐标方程
            y_segment = W_lower[i] + k * (t_segment - i)

            # 在中间的所有点上，直线不能高过上边界，不能低过下边界
            segment_ok = np.all(y_segment <= W_upper[t_start:t_end + 1] + eps) and np.all(
                y_segment >= W_lower[t_start:t_end + 1] - eps)
            if not segment_ok:
                continue

            # --- 检查 2：邻边斜率乘积判据 (k_左 - k) * (k_右 - k) <= 0 ---

            # A. 针对下边界上的触点 i (由于是下边界的上凸峰顶)
            if i > 0 and i < T - 1:
                k_left_i = W_lower[i] - W_lower[i - 1]  # 下边界左邻边
                k_right_i = W_lower[i + 1] - W_lower[i]  # 下边界右邻边
                pt_i_ok = (k_left_i - k) * (k_right_i - k) <= eps
            else:
                pt_i_ok = True  # 边界点放行

            # B. 针对上边界上的触点 j (由于是上边界的下凸谷底，且最后一个点 T-1 免检)
            if j == T - 1:
                pt_j_ok = True  # 最后一个点不检验
            elif j > 0 and j < T - 1:
                k_left_j = W_upper[j] - W_upper[j - 1]  # 上边界左邻边
                k_right_j = W_upper[j + 1] - W_upper[j]  # 上边界右邻边
                pt_j_ok = (k_left_j - k) * (k_right_j - k) <= eps
            else:
                pt_j_ok = True

            # 两端点的切点特性全部满足，且中间不穿墙
            if pt_i_ok and pt_j_ok:
                valid_tangents.append((k, i, j))

    if not valid_tangents:
        print("❌ 老老实实遍历完所有组合，未找到符合定义的跨边界公切线。")
        return None

    # 水库的最枯水限制决定了保证流量，从合法的切线中选取最严苛的
    best_k, best_i, best_j = min(valid_tangents, key=lambda x: x[0])
    QH = Q0 + best_k

    # ==========================================
    # 📊 真正的跨线公切线作图
    # ==========================================
    plt.figure(figsize=(10, 5.5), dpi=100)
    plt.plot(W_upper, label="差积曲线上边界 ($W_{upper}$)", color='#1f77b4', linewidth=2)
    plt.plot(W_lower, label="差积曲线下边界 ($W_{lower}$)", color='#1f77b4', linestyle='--', alpha=0.6)

    # 绘制延伸到全局的真正公切线
    line_y = W_lower[best_i] + best_k * (t_all - best_i)
    plt.plot(t_all, line_y, color='red', linewidth=3, label=f"真正公切线 (k={best_k:.2f})")

    # 标出两个完全处于不同曲线上的切点
    plt.scatter(best_i, W_lower[best_i], color='red', s=90, zorder=5, label="下边界切点 (上凸峰)")
    plt.scatter(best_j, W_upper[best_j], color='darkred', s=90, zorder=5, label="上边界切点 (下凸谷)")

    plt.title(f"两独立数组遍历法 ($V$={V}, 求解 $Q_H$={QH:.2f})", fontsize=13, fontweight='bold')
    plt.xlabel("时间 (t)")
    plt.ylabel("差积水量")
    plt.grid(True, linestyle=':', alpha=0.5)
    plt.legend(loc='best')

    plt.tight_layout()
    plt.show()

    print(f"✅ 成功锁定！下边界切点(峰): 第 {best_i} 月 -> 上边界切点(谷): 第 {best_j} 月")
    return {"QH": QH, "k": best_k}


if __name__ == "__main__":
    honest_two_curve_tangent("data.csv", V=150)
