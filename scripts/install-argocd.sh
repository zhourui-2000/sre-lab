#!/bin/bash
# ─────────────────────────────────────────────────────────────────────
# 安装 / 升级 ArgoCD（幂等）
#
# 设计要点：
#   ① helm 与 chart **都钉版本**，chart 还钉 sha256 —— 校验不过就停手，不"差不多就行"
#   ② chart 从 GitHub releases 取（服务器实测 30 KB/s，237 KB 约 8 秒；可接受）
#   ③ helm 二进制从华为云镜像取（get.helm.sh 也可，但镜像更快）
#   ④ 真正的配置在 /opt/sre-lab/k8s/argocd/values.yaml —— 这个脚本只负责取包与调用
#   ⑤ 幂等：helm upgrade --install，重复执行等价于升级
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

CHART_VER="10.10.5"          # argo-cd chart 版本 ↔ ArgoCD appVersion v3.5.5
CHART_SHA256="ba6447eeed42bc41d1f0527721047b236304e97669a7b6286d02be4a1644ba7a"
CHART_URL="https://github.com/argoproj/argo-helm/releases/download/argo-cd-${CHART_VER}/argo-cd-${CHART_VER}.tgz"

HELM_VER="v3.18.4"
HELM_URL="https://mirrors.huaweicloud.com/helm/${HELM_VER}/helm-${HELM_VER}-linux-amd64.tar.gz"

REPO="/opt/sre-lab"
WORK="/root/argocd-install"
NS="argocd"

mkdir -p "${WORK}"
cd "${WORK}"

# ── 1. helm 二进制 ────────────────────────────────────────────────
if ! command -v helm >/dev/null 2>&1; then
  echo "==> 安装 helm ${HELM_VER}"
  curl -sSL -o helm.tgz "${HELM_URL}"
  tar xzf helm.tgz
  install -m 0755 linux-amd64/helm /usr/local/bin/helm
  rm -rf helm.tgz linux-amd64
fi
printf 'helm: '; helm version --short

# ── 2. chart 包（带校验）──────────────────────────────────────────
if [ ! -f "argo-cd-${CHART_VER}.tgz" ]; then
  echo "==> 下载 chart ${CHART_VER}"
  curl -sSL -o "argo-cd-${CHART_VER}.tgz" "${CHART_URL}"
fi

echo "==> 校验 sha256"
ACTUAL=$(sha256sum "argo-cd-${CHART_VER}.tgz" | cut -d' ' -f1)
if [ "${ACTUAL}" != "${CHART_SHA256}" ]; then
  echo "❌ chart 校验失败"
  echo "   期望 ${CHART_SHA256}"
  echo "   实际 ${ACTUAL}"
  echo "   停手 —— 不要用校验不过的包去装东西。"
  exit 1
fi
echo "   ✅ ${ACTUAL}"

# ── 3. 渲染预检（先看渲染结果，再动集群）───────────────────────────
echo "==> 渲染预检"
if ! helm template argocd "argo-cd-${CHART_VER}.tgz" -n "${NS}" \
      -f "${REPO}/k8s/argocd/values.yaml" > "${WORK}/rendered.yaml" 2>"${WORK}/render.err"; then
  echo "❌ 渲染失败："; sed 's/^/   /' "${WORK}/render.err"
  exit 1
fi
# 判据：必须恰好 4 个常驻工作负载（3 Deployment + 1 StatefulSet），且没有 dex / notifications
N_WORK=$(grep -cE '^kind: (Deployment|StatefulSet)$' "${WORK}/rendered.yaml" || true)
N_DEX=$(grep -cE 'argocd-dex-server|argocd-notifications-controller' "${WORK}/rendered.yaml" || true)
echo "   常驻工作负载 ${N_WORK} 个（期望 4）；dex/notifications 残留 ${N_DEX} 处（期望 0）"
if [ "${N_WORK}" != "4" ] || [ "${N_DEX}" != "0" ]; then
  echo "❌ 渲染结果与预期不符，停手检查 values.yaml"
  exit 1
fi

# ── 4. 安装/升级 ──────────────────────────────────────────────────
echo "==> helm upgrade --install"
helm upgrade --install argocd "argo-cd-${CHART_VER}.tgz" \
  -n "${NS}" --create-namespace \
  -f "${REPO}/k8s/argocd/values.yaml" \
  --wait --timeout 12m

echo
echo "==> 结果"
kubectl -n "${NS}" get deploy,statefulset,pod -o wide
echo
echo "初始 admin 密码（仅在未改密前有效）："
kubectl -n "${NS}" get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' 2>/dev/null | base64 -d; echo
echo
echo "访问方式（在服务器上，另开一个窗口）："
echo "  kubectl -n ${NS} port-forward svc/argocd-server 8080:443"
echo "从 Windows 再套一层隧道：ssh -L 8080:127.0.0.1:8080 lab-node -N"
echo "然后浏览器打开 https://localhost:8080 （自签证书，需点继续）"
