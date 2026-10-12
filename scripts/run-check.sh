#!/usr/bin/env bash
# 在 GitHub Actions (ubuntu-latest) 上运行：下载 subs-check → 测速全部源 → 产出 artifacts/
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

SUBS_CHECK_URL="https://github.com/beck-8/subs-check/releases/latest/download/subs-check_Linux_x86_64.tar.gz"

# 1) 准备 subs-check 二进制
if [ ! -x "$REPO_ROOT/subs-check" ]; then
  echo "==> downloading subs-check..."
  curl -fsSL -o /tmp/subs-check.tar.gz "$SUBS_CHECK_URL"
  tar -xzf /tmp/subs-check.tar.gz -C "$REPO_ROOT"
  chmod +x "$REPO_ROOT/subs-check"
fi
"$REPO_ROOT/subs-check" --help 2>/dev/null | head -5 || true

# 2) 生成配置
OUT_DIR="$REPO_ROOT/artifacts"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR" "$REPO_ROOT/output"
sed "s|{{OUTPUT_DIR}}|$OUT_DIR|g" "$REPO_ROOT/config/base.yaml" > "$REPO_ROOT/config/checker.yaml"

# 3) 跑一轮完整检测（后台 + 轮询日志）
rm -f "$REPO_ROOT/check.log"
"$REPO_ROOT/subs-check" -f "$REPO_ROOT/config/checker.yaml" > "$REPO_ROOT/check.log" 2>&1 &
SUBS_PID=$!

cleanup() { kill "$SUBS_PID" 2>/dev/null || true; }
trap cleanup EXIT

echo "==> waiting for check cycle to finish (max ~40 min)"
found=0
for _ in $(seq 1 480); do
  if grep -q "检测完成\|检测代理失败\|保存.*失败" "$REPO_ROOT/check.log" 2>/dev/null; then
    found=1
    break
  fi
  sleep 5
done

if [ "$found" -eq 0 ]; then
  echo "!! check cycle did not finish in time, killing"
  kill "$SUBS_PID" 2>/dev/null || true
  tail -80 "$REPO_ROOT/check.log"
  exit 1
fi

# 让 SaveConfig / SubStore 落盘
sleep 15
kill "$SUBS_PID" 2>/dev/null || true
wait "$SUBS_PID" 2>/dev/null || true
trap - EXIT

echo "==> artifacts:"
ls -la "$OUT_DIR" || true
echo "==> results.json location:"
find "$REPO_ROOT" -name "results.json" -newer "$REPO_ROOT/config/base.yaml" 2>/dev/null || true

if [ ! -s "$OUT_DIR/all.yaml" ]; then
  echo "!! all.yaml is empty, check log:"; tail -60 "$REPO_ROOT/check.log"
  exit 1
fi
echo "==> done"