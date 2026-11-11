#!/usr/bin/env bash
# M9：为 Capacitor 生成 android/ 与 ios/ 原生工程（一次性）。
#
# 前置：本机 Node 20+、npm 可访问 registry（或已配置镜像）、
#       iOS 侧需 Xcode（本机未安装完整 Xcode，iOS 需在装好 Xcode 的机器上执行）。
#
# 用法：./scripts/cap-add-platforms.sh
set -euo pipefail
cd "$(dirname "$0")/../frontend"

echo "== 1/5 安装平台包（不写入 Web 构建依赖，避免镜像构建时需要联网） =="
# @capacitor/android|ios 版本必须与 @capacitor/core 一致
npm install @capacitor/android@8.6.0 @capacitor/ios@8.6.0 --save
# 若只想临时安装、不改 package.json，可加 --no-save；
# 选择 --save 是因为原生工程需要长期保留这两个包

echo "== 2/5 构建前端产物 =="
npm run build

echo "== 3/5 添加 Android 平台 =="
npx cap add android

echo "== 4/5 添加 iOS 平台（需要 macOS + Xcode） =="
npx cap add ios || echo "! iOS 平台添加失败（通常是未安装 Xcode），可稍后在装好 Xcode 的机器上重跑"

echo "== 5/5 同步产物与配置 =="
npx cap sync

cat <<'EOF'

完成。还需手工确认三处原生配置（见 docs/DEVELOPMENT_PLAN.md 的 M9 段）：
  1. android/app/src/main/AndroidManifest.xml 的 application 上加 android:usesCleartextTraffic="true"
  2. 同一文件的权限：<uses-permission android:name="android.permission.CAMERA"/>
  3. ios/App/App/Info.plist 加 NSCameraUsageDescription 与 NSAppTransportSecurity(NSAllowsArbitraryLoads=true)

调试：npx cap open android / npx cap open ios
EOF
