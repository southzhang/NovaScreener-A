#!/bin/bash
# 量化盯盘选股 V10 — 创建 macOS .app 包
set -e

APP_NAME="量化盯盘选股V10"
DIST_DIR="dist"
APP_DIR="$DIST_DIR/$APP_NAME.app"
INTERNAL_DIR="$APP_DIR/Contents/Resources"

echo "🍎 创建 macOS .app 包..."

# 清理旧的 .app
rm -rf "$APP_DIR"

# 创建 .app 结构
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# 复制可执行文件和 _internal 到 Resources
cp "$DIST_DIR/$APP_NAME/$APP_NAME" "$APP_DIR/Contents/Resources/"
cp -R "$DIST_DIR/$APP_NAME/_internal" "$APP_DIR/Contents/Resources/"
chmod +x "$APP_DIR/Contents/Resources/$APP_NAME"

# 创建 Info.plist
cat > "$APP_DIR/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>launch.sh</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>com.southzhang.quant-watchdog</string>
    <key>CFBundleName</key>
    <string>量化盯盘选股V10</string>
    <key>CFBundleDisplayName</key>
    <string>量化盯盘选股V10</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSRequiresAquaSystemAppearance</key>
    <false/>
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.finance</string>
</dict>
</plist>
EOF

# 创建启动脚本（包装器）
cat > "$APP_DIR/Contents/MacOS/launch.sh" << 'LAUNCH'
#!/bin/bash
# 获取 .app 包内的 Resources 目录
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
RESOURCES_DIR="$DIR/../Resources"

# 设置环境变量
export DYLD_LIBRARY_PATH="$RESOURCES_DIR/_internal:$DYLD_LIBRARY_PATH"
export PYTHONPATH="$RESOURCES_DIR/_internal:$PYTHONPATH"

# 切换到 Resources 目录（PyInstaller 需要在这里找到 _internal）
cd "$RESOURCES_DIR"

# 启动应用
exec "./量化盯盘选股V10" "$@"
LAUNCH
chmod +x "$APP_DIR/Contents/MacOS/launch.sh"

echo "✅ .app 包创建完成: $APP_DIR"
echo "📊 应用大小: $(du -sh "$APP_DIR" | cut -f1)"
echo ""
echo "🚀 使用方式:"
echo "   双击 $APP_DIR 即可运行"
echo "   或: open $APP_DIR"
