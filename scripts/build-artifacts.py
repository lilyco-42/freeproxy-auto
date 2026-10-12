#!/usr/bin/env python3
"""后处理：把 subs-check 的 artifacts/ 打包为用户可订阅的产物 + 按用途分类。

输入:
  artifacts/all.yaml          -- 存活节点列表 (proxies，节点名含速度/媒体/纯净度标签)
  artifacts/base64.txt        -- base64 通用订阅（可选）
  <repo>/config/../results.json -- 结构化明细（测速/媒体/unlock/ipRisk，可选）

输出 (output/):
  clash.yaml   -- 全量 Clash/Mihomo 订阅（proxies + proxy-groups + rules）
  youtube.yaml -- 仅 YouTube 解锁节点（节点名含 YT- 标签）
  claude.yaml  -- 仅 Claude 可用节点（节点名含 CL- 标签）
  openai.yaml  -- 仅 OpenAI/ChatGPT 可用节点（节点名含 GPT 标签）
  clean.yaml   -- 仅纯净 IP 节点（Scamalytics fraud score <= CLEAN_SCORE_MAX）
  ultra_clean.yaml -- 仅严格纯净节点（Scamalytics fraud score <= CLEAN_SCORE_STRICT 极佳段）
  premium.yaml -- 精品节点（YouTube+Claude+OpenAI 全解锁 且 纯净度 ≤ CLEAN_SCORE_STRICT）
  v2ray.txt    -- base64 通用订阅
  status.md    -- 节点统计报告（分类数量 + 纯净度分布 + 速度 Top）
"""
import argparse
import datetime
import json
import os
import re
import sys

try:
    import yaml
except ImportError:  # Action 里先 pip install pyyaml
    print("PyYAML 未安装，请先执行: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# Scamalytics fraud score 合格线：0-15 极佳 / 15-40 有风控风险 / >40 基本别指望
CLEAN_SCORE_MAX = 40
# 严格纯净档：仅极佳段（注册账号/AI 场景首选）
CLEAN_SCORE_STRICT = 15

AUTO = "🔍 自动选择"
MANUAL = "🎯 手动选择"


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
    groups = [
        {
            "name": AUTO,
            "type": "url-test",
            "url": "http://www.gstatic.com/generate_204",
            "interval": 300,
            "tolerance": 50,
            "proxies": names,
        },
        {
            "name": MANUAL,
            "type": "select",
            "proxies": [AUTO, "DIRECT"] + names,
        },
    ]
    rules = ["GEOIP,CN,DIRECT", "MATCH,%s" % AUTO]
    return yaml.safe_dump(
        {"proxies": proxies, "proxy-groups": groups, "rules": rules},
        allow_unicode=True,
        sort_keys=False,
        width=4096,
    )


def _speed_of(n):
    try:
        return int(n.get("speed") or 0)
    except (TypeError, ValueError):
        return 0


def collect_node_records(results):
    """把 results.json 的 nodes[] 建成 name -> 结构化记录 的字典。"""
    nodes = results.get("nodes", []) if isinstance(results, dict) else []
    recs = {}
    for n in nodes:
        name = n.get("name")
        if not name:
            continue
        media = {}
        for m in n.get("media") or []:
            media[m.get("platform")] = m.get("tag") or ""
        ipr = n.get("ipRisk") or ""
        ipr_num = None
        if isinstance(ipr, str):
            m = re.match(r"^(\d{1,3})%?$", ipr.strip())
            if m:
                ipr_num = int(m.group(1))
        recs[name] = {
            "media": media,
            "iprisk": ipr_num,
            "country": n.get("country") or "",
            "speed": _speed_of(n),
        }
    return recs


def classify(proxies, recs):
    """返回 {filename: (title, proxies子集, note)} 及每类数量描述。"""
    cats = {
        "youtube": ("🎬 YouTube 解锁", set()),
        "claude": ("🤖 Claude 可用", set()),
        "openai": ("💬 OpenAI 可用", set()),
        "clean": ("🧼 纯净 IP", set()),
        "ultra_clean": ("💎 严格纯净 IP", set()),
        "premium": ("🏆 精品节点", set()),
    }
    # 先算出每轴命中，再组合（premium 需要四轴同时成立）
    for p in proxies:
        name = p.get("name", "")
        rec = recs.get(name, {})
        media = rec.get("media", {})
        iprisk = rec.get("iprisk")

        def has_tag(key):
            return bool(media.get(key)) or f"|{key}-" in name

        is_yt = has_tag("youtube") or "|YT-" in name
        is_cl = has_tag("claude") or "|CL-" in name
        is_gpt = bool(media.get("openai")) or "|GPT" in name or "|GPT⁺" in name

        if is_yt:
            cats["youtube"][1].add(name)
        if is_cl:
            cats["claude"][1].add(name)
        if is_gpt:
            cats["openai"][1].add(name)

        # 纯净 IP：优先 results 里的数值；缺失则从名字解析 "|NN%"
        risk = iprisk
        if risk is None:
            m = re.search(r"\|\s*(\d{1,3})%", name)
            if m:
                risk = int(m.group(1))
        if risk is not None and risk <= CLEAN_SCORE_MAX:
            cats["clean"][1].add(name)
        if risk is not None and risk <= CLEAN_SCORE_STRICT:
            cats["ultra_clean"][1].add(name)
        # 精品：YouTube + Claude + OpenAI 三平台全解锁，且严格纯净（≤15）
        if is_yt and is_cl and is_gpt and risk is not None and risk <= CLEAN_SCORE_STRICT:
            cats["premium"][1].add(name)

    named = {p.get("name") for p in proxies}
    out = {}
    for key, (title, members) in cats.items():
        subset = [p for p in proxies if p.get("name") in members]
        note = {
            "youtube": "仅含 YouTube Premium 解锁节点（可看 YouTube）",
            "claude": "仅含 Claude 可用节点（claude.ai 地区不在封禁列表）",
            "openai": "仅含 ChatGPT/OpenAI 可用节点（含 Gemini 的 GPT 标签不在此列）",
            "clean": "仅含 Scamalytics 纯净度评分 ≤ %d 的节点（数值越低越干净，0-15 极佳）" % CLEAN_SCORE_MAX,
            "ultra_clean": "仅含 Scamalytics 纯净度评分 ≤ %d 的节点（极佳段，注册账号/AI 首选）" % CLEAN_SCORE_STRICT,
            "premium": "四轴全过：YouTube + Claude + OpenAI 全解锁 且 Scamalytics 评分 ≤ %d（万里挑一，首选）" % CLEAN_SCORE_STRICT,
        }[key]
        out[key] = (title, subset, note)
    return cats, out


def write_category(out_dir, filename, title, subset, note, stamp):
    if not subset:
        print("!! %s 无节点，保留上次文件" % filename, file=sys.stderr)
        return False
    header = (
        "# freeproxy-auto · %s\n"
        "# 节点数: %d · 生成时间: %s\n"
        "# %s\n"
        "# 警告: 免费公共节点存在隐私/蜜罐风险\n\n"
    ) % (title, len(subset), stamp, note)
    with open(os.path.join(out_dir, filename), "w", encoding="utf-8") as f:
        f.write(header + build_clash_yaml(subset))
    return True


def main():
    global CLEAN_SCORE_MAX
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--clean-max", type=int, default=CLEAN_SCORE_MAX)
    args = ap.parse_args()

    CLEAN_SCORE_MAX = args.clean_max

    root = args.repo_root
    art = os.path.join(root, "artifacts")
    out_dir = os.path.join(root, "output")
    os.makedirs(out_dir, exist_ok=True)

    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")

    proxies = load_proxies(os.path.join(art, "all.yaml"))
    results = load_results(root)
    recs = collect_node_records(results)
    checked_at = results.get("checkedAt", "") if isinstance(results, dict) else ""

    # ---- 同身份去重：server+port+type+凭据 相同视为同一节点，保留速度标签最高者 ----
    # 43 个源大量互相转载，同一 IP:port 会以不同测速快照出现多次（差可达 25 倍），误导用户
    def _name_speed(n):
        m = re.match(r".*?\|([\d.]+)(KB/s|MB/s)\|", n or "")
        if not m:
            return 0
        v = float(m.group(1))
        return int(v * 1024) if m.group(2) == "MB/s" else int(v)

    seen = {}
    uniq = []
    dup_dropped = 0
    for p in proxies:
        key = (
            p.get("server"),
            p.get("port"),
            p.get("type"),
            p.get("uuid") or p.get("password") or p.get("username") or "",
        )
        prev = seen.get(key)
        if prev is None:
            seen[key] = p
            uniq.append(p)
        else:
            dup_dropped += 1
            if _name_speed(p.get("name")) > _name_speed(prev.get("name")):
                uniq[uniq.index(prev)] = p
                seen[key] = p
    if dup_dropped:
        print("==> 同身份去重: %d -> %d (移除冗余 %d)" % (len(proxies), len(uniq), dup_dropped))
        proxies = uniq

    # ---- 全量 clash.yaml ----
    if proxies:
        header = (
            "# freeproxy-auto 自动生成 · 每 3 小时更新\n"
            "# 节点数: %d · 生成时间: %s\n"
            "# 节点名标签: 速度|媒体解锁(YT-区/CL-区/GPT/GPT⁺/NF/D+/GM)|纯净度%%\n"
            "# 警告: 免费公共节点存在隐私/蜜罐风险，请勿在通过它们的连接中登录或传输敏感数据\n\n"
        ) % (len(proxies), stamp)
        with open(os.path.join(out_dir, "clash.yaml"), "w", encoding="utf-8") as f:
            f.write(header + build_clash_yaml(proxies))
    else:
        print("!! 无一存活节点，保留上次 output/clash.yaml", file=sys.stderr)

    # ---- 分类订阅 ----
    cats, cat_files = classify(proxies, recs)
    for key, (title, subset, note) in cat_files.items():
        write_category(out_dir, "%s.yaml" % key, title, subset, note, stamp)

    # ---- v2ray.txt ----
    b64_src = os.path.join(art, "base64.txt")
    if os.path.isfile(b64_src):
        with open(b64_src, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        with open(os.path.join(out_dir, "v2ray.txt"), "w", encoding="utf-8") as f:
            f.write(content)

    # ---- status.md ----
    yt_n = len(cats["youtube"][1])
    cl_n = len(cats["claude"][1])
    op_n = len(cats["openai"][1])
    clean_n = len(cats["clean"][1])
    ultra_n = len(cats["ultra_clean"][1])
    prem_n = len(cats["premium"][1])

    lines = [
        "# 📡 节点状态",
        "",
        "| 项目 | 数值 |",
        "|---|---|",
        "| 生成时间 | %s |" % stamp,
        "| 存活节点数 | %d |" % len(proxies),
        "| 去重移除 | %d |" % dup_dropped,
        "| 测速节点明细 | %d |" % len(recs),
        "| 🏆 精品(YT+CL+GPT+纯净≤%d) | %d |" % (CLEAN_SCORE_STRICT, prem_n),
        "| 🎬 YouTube 解锁 | %d |" % yt_n,
        "| 🤖 Claude 可用 | %d |" % cl_n,
        "| 💬 OpenAI 可用 | %d |" % op_n,
        "| 🧼 纯净 IP(评分≤%d) | %d |" % (CLEAN_SCORE_MAX, clean_n),
        "| 💎 严格纯净 IP(评分≤%d) | %d |" % (CLEAN_SCORE_STRICT, ultra_n),
    ]
    if checked_at:
        lines.append("| 检测时间(check) | %s |" % checked_at)
    lines.append("")

    # 纯净度分布
    scores = [r["iprisk"] for r in recs.values() if r["iprisk"] is not None]
    if scores:
        low = sum(1 for s in scores if s <= 15)
        mid = sum(1 for s in scores if 15 < s <= CLEAN_SCORE_MAX)
        high = sum(1 for s in scores if s > CLEAN_SCORE_MAX)
        lines.append("## 🧼 纯净度分布（Scamalytics fraud score，数值越低越纯净）")
        lines.append("")
        lines.append("| 档位 | 数量 |")
        lines.append("|---|---|")
        lines.append("| 0-15（极佳，适合注册账号/AI） | %d |" % low)
        lines.append("| 16-%d（可通过测试，有风控风险） | %d |" % (CLEAN_SCORE_MAX, mid))
        lines.append("| >%d（污染/机房高利） | %d |" % (CLEAN_SCORE_MAX, high))
        lines.append("")

    # 国家/地区分布（取存活节点名首段旗帜后的国家码，results.country 优先）
    from collections import Counter
    cc = Counter()
    for n in (results.get("nodes", []) if isinstance(results, dict) else []):
        c = (n.get("country") or "").strip().upper()
        if c:
            cc[c] += 1
    if cc:
        lines.append("## 🌍 国家/地区分布 Top 15")
        lines.append("")
        lines.append("| 地区 | 节点数 |")
        lines.append("|---|---|")
        for code, cnt in cc.most_common(15):
            lines.append("| %s | %d |" % (code, cnt))
        lines.append("")

    def speed_of(n):
        try:
            return int(n.get("speed") or 0)
        except (TypeError, ValueError):
            return 0

    good = [n for n in (results.get("nodes", []) if isinstance(results, dict) else []) if speed_of(n) > 0]
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

    with open(os.path.join(out_dir, "status.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("==> output/ 产物:")
    for fn in sorted(os.listdir(out_dir)):
        print("   ", fn, os.path.getsize(os.path.join(out_dir, fn)))
    print("==> 分类: youtube=%d claude=%d openai=%d clean=%d ultra_clean=%d premium=%d (全量=%d)"
          % (yt_n, cl_n, op_n, clean_n, ultra_n, prem_n, len(proxies)))


if __name__ == "__main__":
    main()