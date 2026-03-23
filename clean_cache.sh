#!/bin/bash

# ========================================
# 清理所有緩存腳本（全域版本）
# 此腳本會清理整個專案中所有類型的緩存文件
# 不限定特定目錄，徹底清理所有緩存
# ========================================

set -e  # 遇到錯誤立即停止

echo "🧹 開始全域清理所有緩存..."
echo "================================"

# 記錄腳本執行位置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ========================================
# Next.js / React 緩存清理
# ========================================
echo ""
echo "⚛️  清理 Next.js / React 緩存..."

# 清理 .next 目錄（整個專案）
NEXT_COUNT=$(find . -type d -name ".next" 2>/dev/null | wc -l | tr -d ' ')
if [ "$NEXT_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $NEXT_COUNT 個 .next 目錄"
    find . -type d -name ".next" -exec rm -rf {} + 2>/dev/null || true
else
    echo "  - 沒有 .next 目錄，跳過"
fi

# 清理 .turbo 目錄
TURBO_COUNT=$(find . -type d -name ".turbo" 2>/dev/null | wc -l | tr -d ' ')
if [ "$TURBO_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $TURBO_COUNT 個 .turbo 目錄"
    find . -type d -name ".turbo" -exec rm -rf {} + 2>/dev/null || true
else
    echo "  - 沒有 .turbo 目錄，跳過"
fi

# 清理 out 目錄
OUT_COUNT=$(find . -type d -name "out" 2>/dev/null | wc -l | tr -d ' ')
if [ "$OUT_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $OUT_COUNT 個 out 目錄"
    find . -type d -name "out" -exec rm -rf {} + 2>/dev/null || true
else
    echo "  - 沒有 out 目錄，跳過"
fi

# 清理 build 目錄
BUILD_COUNT=$(find . -type d -name "build" 2>/dev/null | wc -l | tr -d ' ')
if [ "$BUILD_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $BUILD_COUNT 個 build 目錄"
    find . -type d -name "build" -exec rm -rf {} + 2>/dev/null || true
else
    echo "  - 沒有 build 目錄，跳過"
fi

# 清理 dist 目錄
DIST_COUNT=$(find . -type d -name "dist" 2>/dev/null | wc -l | tr -d ' ')
if [ "$DIST_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $DIST_COUNT 個 dist 目錄"
    find . -type d -name "dist" -exec rm -rf {} + 2>/dev/null || true
else
    echo "  - 沒有 dist 目錄，跳過"
fi

# ========================================
# TypeScript 緩存清理
# ========================================
echo ""
echo "📘 清理 TypeScript 緩存..."

# 清理 tsconfig.tsbuildinfo
TSBUILDINFO_COUNT=$(find . -name "tsconfig.tsbuildinfo" -o -name "*.tsbuildinfo" 2>/dev/null | wc -l | tr -d ' ')
if [ "$TSBUILDINFO_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $TSBUILDINFO_COUNT 個 TypeScript 緩存文件"
    find . \( -name "tsconfig.tsbuildinfo" -o -name "*.tsbuildinfo" \) -delete 2>/dev/null || true
else
    echo "  - 沒有 TypeScript 緩存，跳過"
fi

# ========================================
# Python 緩存清理
# ========================================
echo ""
echo "🐍 清理 Python 緩存..."

# 清理 __pycache__
PYCACHE_COUNT=$(find . -type d -name "__pycache__" 2>/dev/null | wc -l | tr -d ' ')
if [ "$PYCACHE_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $PYCACHE_COUNT 個 __pycache__ 目錄"
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
else
    echo "  - 沒有 __pycache__ 目錄，跳過"
fi

# 清理 .pyc 文件
PYC_COUNT=$(find . -type f -name "*.pyc" 2>/dev/null | wc -l | tr -d ' ')
if [ "$PYC_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $PYC_COUNT 個 .pyc 文件"
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
else
    echo "  - 沒有 .pyc 文件，跳過"
fi

# 清理 .pyo 文件
PYO_COUNT=$(find . -type f -name "*.pyo" 2>/dev/null | wc -l | tr -d ' ')
if [ "$PYO_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $PYO_COUNT 個 .pyo 文件"
    find . -type f -name "*.pyo" -delete 2>/dev/null || true
else
    echo "  - 沒有 .pyo 文件，跳過"
fi

# 清理 .pytest_cache
PYTEST_COUNT=$(find . -type d -name ".pytest_cache" 2>/dev/null | wc -l | tr -d ' ')
if [ "$PYTEST_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $PYTEST_COUNT 個 .pytest_cache 目錄"
    find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
else
    echo "  - 沒有 .pytest_cache 目錄，跳過"
fi

# 清理 *.egg-info
EGGINFO_COUNT=$(find . -type d -name "*.egg-info" 2>/dev/null | wc -l | tr -d ' ')
if [ "$EGGINFO_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $EGGINFO_COUNT 個 .egg-info 目錄"
    find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
else
    echo "  - 沒有 .egg-info 目錄，跳過"
fi

# ========================================
# 通用緩存目錄清理
# ========================================
echo ""
echo "📦 清理通用緩存目錄..."

# 清理 .cache 目錄
CACHE_COUNT=$(find . -type d -name ".cache" 2>/dev/null | wc -l | tr -d ' ')
if [ "$CACHE_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $CACHE_COUNT 個 .cache 目錄"
    find . -type d -name ".cache" -exec rm -rf {} + 2>/dev/null || true
else
    echo "  - 沒有 .cache 目錄，跳過"
fi

# 清理 .parcel-cache
PARCEL_COUNT=$(find . -type d -name ".parcel-cache" 2>/dev/null | wc -l | tr -d ' ')
if [ "$PARCEL_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $PARCEL_COUNT 個 .parcel-cache 目錄"
    find . -type d -name ".parcel-cache" -exec rm -rf {} + 2>/dev/null || true
else
    echo "  - 沒有 .parcel-cache 目錄，跳過"
fi

# 清理 .vite 目錄
VITE_COUNT=$(find . -type d -name ".vite" 2>/dev/null | wc -l | tr -d ' ')
if [ "$VITE_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $VITE_COUNT 個 .vite 目錄"
    find . -type d -name ".vite" -exec rm -rf {} + 2>/dev/null || true
else
    echo "  - 沒有 .vite 目錄，跳過"
fi

# ========================================
# 系統緩存清理
# ========================================
echo ""
echo "🔧 清理系統緩存..."

# 清理 .DS_Store (macOS)
DS_STORE_COUNT=$(find . -name ".DS_Store" 2>/dev/null | wc -l | tr -d ' ')
if [ "$DS_STORE_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $DS_STORE_COUNT 個 .DS_Store 文件"
    find . -name ".DS_Store" -delete 2>/dev/null || true
else
    echo "  - 沒有 .DS_Store 文件，跳過"
fi

# 清理 Thumbs.db (Windows)
THUMBS_COUNT=$(find . -name "Thumbs.db" 2>/dev/null | wc -l | tr -d ' ')
if [ "$THUMBS_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $THUMBS_COUNT 個 Thumbs.db 文件"
    find . -name "Thumbs.db" -delete 2>/dev/null || true
else
    echo "  - 沒有 Thumbs.db 文件，跳過"
fi

# ========================================
# 日誌文件清理
# ========================================
echo ""
echo "📝 清理日誌文件..."

# 清理 npm/yarn 日誌
LOG_COUNT=$(find . \( -name "npm-debug.log" -o -name "yarn-error.log" -o -name "yarn-debug.log" -o -name "pnpm-debug.log" \) 2>/dev/null | wc -l | tr -d ' ')
if [ "$LOG_COUNT" -gt 0 ]; then
    echo "  ✓ 刪除 $LOG_COUNT 個日誌文件"
    find . \( -name "npm-debug.log" -o -name "yarn-error.log" -o -name "yarn-debug.log" -o -name "pnpm-debug.log" \) -delete 2>/dev/null || true
else
    echo "  - 沒有日誌文件，跳過"
fi

# ========================================
# 完成
# ========================================
echo ""
echo "================================"
echo "✅ 全域緩存清理完成！"
echo ""
echo "📋 保留的重要文件/目錄："
echo "  ✓ node_modules (依賴包)"
echo "  ✓ pnpm-lock.yaml / package-lock.json (鎖定文件)"
echo "  ✓ package.json (包配置)"
echo "  ✓ .git (版本控制)"
echo "  ✓ 所有源代碼文件"
echo ""
echo "�️  已清理的緩存類型："
echo "  • Next.js/React: .next, .turbo, out, build, dist"
echo "  • TypeScript: *.tsbuildinfo"
echo "  • Python: __pycache__, *.pyc, *.pyo, .pytest_cache, *.egg-info"
echo "  • 通用緩存: .cache, .parcel-cache, .vite"
echo "  • 系統文件: .DS_Store, Thumbs.db"
echo "  • 日誌文件: npm-debug.log, yarn-error.log 等"
echo ""
echo "💡 提示："
echo "  - 下次運行開發服務器時，緩存會自動重新生成"
echo "  - 如果需要重新安裝依賴，請運行 'pnpm install'"
echo ""
