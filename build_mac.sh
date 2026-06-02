#!/bin/bash
# 量化盯盘选股 V10 — 桌面版构建脚本
# 用法: ./build_mac.sh

set -e

echo "🔨 开始构建量化盯盘选股 V10 桌面版..."

# 检查 PyInstaller
if ! command -v pyinstaller &> /dev/null; then
    echo "📦 安装 PyInstaller..."
    pip install pyinstaller
fi

# 清理旧的构建
echo "🧹 清理旧构建..."
rm -rf build/ dist/

# 构建
echo "🏗️ 构建中（约2-5分钟）..."
pyinstaller quant-watchdog.spec --clean --noconfirm

# 检查结果
APP_PATH="dist/量化盯盘选股V10"
if [ -d "$APP_PATH" ]; then
    echo ""
    echo "✅ 构建成功！"
    echo "📁 输出目录: $APP_PATH"
    echo "📊 应用大小: $(du -sh "$APP_PATH" | cut -f1)"
    echo ""
    echo "🚀 运行方式:"
    echo "   cd $APP_PATH && ./量化盯盘选股V10"
    echo ""
    echo "💡 提示: 可以将整个文件夹拷贝到其他 Mac 上直接运行"
else
    echo "❌ 构建失败，请检查错误信息"
    exit 1
fi
