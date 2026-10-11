#!/usr/bin/env python3
"""后处理：把 subs-check 的 artifacts/ 打包为用户可订阅的产物。

输入:
  artifacts/all.yaml      -- 存活节点列表 (proxies)
  artifacts/base64.txt    -- base64 通用订阅（可选）
  artifacts/mihomo.yaml   -- mihomo 订阅（可选）
  <repo>/config/results.json -- 测速/延迟明细（可选，用于生成状态报告）

输出 (output/):
  clash.yaml   -- 完整 Clash/Mihomo 订阅（proxies + proxy-groups + rules）
  v2ray.txt    -- base64 通用订阅
  status.md    -- 节点统计报告（也用于写 README 徽章）
"""
import argparse
import datetime
import json
import os
import sys

try:
    import yaml
except ImportError:  # Action 里先 pip install pyyaml
    print("PyYAML 未安装，请先执行: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


def load_proxies(all_yaml_path):
    if not os.path.isfile(all_yaml_path):
        return []
    with open(all_yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("proxies", []) or []


def load_results(repo_root):
    """results.json 位于 <config_dir>/cache/<name>/results.json，递归查找。"""
    candidates = []
    for dirpath, _dirnames, filenames in os.walk(os.path.join(repo_root, "config")):
        if "results.json" in filenames:
            candidates.append(os.path.join(dirpath, "results.json"))
    if not candidates:
        for dirpath, _dirnames, filenames in os.walk(repo_root):
            if "results.json" in filenames:
                candidates.append(os.path.join(dirpath, "results.json"))
    if not candidates:
        return {}
    path = sorted(candidates, key=len)[0]
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def proxy_names(proxies):
    out = []
    for p in proxies:
        if isinstance(p, dict) and "name" in p:
            out.append(p["name"])
    return out


def build_clash_yaml(proxies):
    names = proxy_names(proxies)
    auto = "🔍 自动选择"
    manual = "🎯 手动选择"
    groups = [
        {
            "name": auto,
            "type": "url-test",
            "url": "http://www.gstatic.com/generate_204",
            "interval": 300,
            "tolerance": 50,
            "proxies": names,
        },
        {
            "name": manual,
            "type": "select",
            "proxies": [auto, "DIRECT"] + names,
        },
    ]
    rules = ["GEOIP,CN,DIRECT", "MATCH,%s" % auto]
    buf = yaml.safe_dump(
        {
            "proxies": proxies,
            "proxy-groups": groups,
            "rules": rules,
        },
        allow_unicode=True,
        sort_keys=False,
        width=4096,
    )
    return buf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args()

    root = args.repo_root
    art = os.path.join(root, "artifacts")
    out_dir = os.path.join(root, "output")
    os.makedirs(out_dir, exist_ok=True)

    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")

    proxies = load_proxies(os.path.join(art, "all.yaml"))
    results = load_results(root)
    nodes = results.get("nodes", []) if isinstance(results, dict) else []
    checked_at = results.get("checkedAt", "")

    # ---- clash.yaml ----
    if proxies:
        body = build_clash_yaml(proxies)
        header = (
            "# freeproxy-auto 自动生成 · 每 3 小时更新\n"
            "# 节点数: %d · 生成时间: %s\n"
            "# 警告: 免费公共节点存在隐私/蜜罐风险，请勿在通过它们的连接中登录或传输敏感数据\n\n"
        ) % (len(proxies), stamp)
        with open(os.path.join(out_dir, "clash.yaml"), "w", encoding="utf-8") as f:
            f.write(header + body)
    else:
        print("!! 无一存活节点，保留上次 output/clash.yaml", file=sys.stderr)

    # ---- v2ray.txt ----
    b64_src = os.path.join(art, "base64.txt")
    if os.path.isfile(b64_src):
        with open(b64_src, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        with open(os.path.join(out_dir, "v2ray.txt"), "w", encoding="utf-8") as f:
            f.write(content)

    # ---- status.md ----
    lines = [
        "# 📡 节点状态",
        "",
        "| 项目 | 数值 |",
        "|---|---|",
        "| 生成时间 | %s |" % stamp,
        "| 存活节点数 | %d |" % len(proxies),
        "| 测速节点明细 | %d |" % len(nodes),
    ]
    if checked_at:
        lines.append("| 检测时间(check) | %s |" % checked_at)
    lines.append("")

    def speed_of(n):
        try:
            s = int(n.get("speed") or 0)
            return s
        except (TypeError, ValueError):
            return 0

    good = [n for n in nodes if speed_of(n) > 0]
    good.sort(key=speed_of, reverse=True)
    if good:
        lines.append("## ⚡ 速度 Top 20")
        lines.append("")
        lines.append("| 排名 | 名称 | 速度 (KB/s) | 地区 |")
        lines.append("|---|---|---|---|")
        for i, n in enumerate(good[:20], 1):
            name = (n.get("name") or "").replace("|", "\\|")
            gb = n.get("country") or n.get("ip") or "-"
            lines.append("| %d | %s | %s | %s |" % (i, name, speed_of(n), gb))
    elif nodes:
        lines.append("暂无数值速度数据（本次可能仅做了连通性检测）。")

    with open(os.path.join(out_dir, "status.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("==> output/ 产物:")
    for fn in sorted(os.listdir(out_dir)):
        print("   ", fn, os.path.getsize(os.path.join(out_dir, fn)))
    print("==> 存活节点:", len(proxies))


if __name__ == "__main__":
    main()