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

# ── 0. kubeconfig：helm 不会自己去找 k3s 的配置 ────────────────────
# k3s 把 kubeconfig 写在 /etc/rancher/k3s/k3s.yaml（不在 ~/.kube/config），
# 而 helm 找不到配置时**不报"没有配置"，而是退回默认地址 localhost:8080**，
# 于是报出极具误导性的 "Kubernetes cluster unreachable: dial tcp [::1]:8080"。
# 这里显式指定，避免依赖"某个 shell 里恰好 export 过"。
# 注：不创建 ~/.kube/config —— 那是服务器上的手工产物，会变成 IaC 之外的漂移。
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"

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

# ── 2. chart 包（多通道 + 校验）────────────────────────────────────
# GitHub releases 从这台服务器是**间歇性**的：实测 3 次里 1 次 200（约 8 KB/s）、
# 1 次 connection reset、1 次空回复。所以不能只试一个地址。
# 因为 sha256 已钉死，**任何一个通道拿到的包都必须过校验才用** ——
# 这才是能安心使用镜像/代理的前提。
CHART_FILE="argo-cd-${CHART_VER}.tgz"
SOURCES=(
  "${CHART_URL}"                                        # 官方（有时可用）
  "https://ghproxy.net/${CHART_URL}"                    # 代理 1（服务器侧实测 200）
  "https://gh-proxy.com/${CHART_URL}"                   # 代理 2（服务器侧实测 200）
)

if [ -f "${CHART_FILE}" ] && [ "$(sha256sum "${CHART_FILE}" | cut -d' ' -f1)" = "${CHART_SHA256}" ]; then
  echo "==> chart 已就位且校验通过，跳过下载"
else
  ok=0
  for src in "${SOURCES[@]}"; do
    echo "==> 尝试下载：$(echo "${src}" | sed 's#https://##;s#/https.*##')"
    rm -f "${CHART_FILE}.part"
    if curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 300 \
         -o "${CHART_FILE}.part" "${src}"; then
      got=$(sha256sum "${CHART_FILE}.part" | cut -d' ' -f1)
      if [ "${got}" = "${CHART_SHA256}" ]; then
        mv "${CHART_FILE}.part" "${CHART_FILE}"
        echo "   ✅ 下载并校验通过"
        ok=1
        break
      fi
      echo "   ⚠️ 下载到了但校验不符（${got:0:16}…），换下一个通道"
    else
      echo "   ⚠️ 该通道失败（curl rc=$?），换下一个通道"
    fi
    rm -f "${CHART_FILE}.part"
  done

  if [ "${ok}" != "1" ]; then
    echo
    echo "❌ 三个通道都失败了。两个可行的手工办法："
    echo "   ① 复用之前下好的包（若有）："
    echo "        cp /tmp/${CHART_FILE} ${WORK}/ && sha256sum ${WORK}/${CHART_FILE}"
    echo "   ② 从别的机器下载后 scp 到 ${WORK}/，再确认 sha256 = ${CHART_SHA256}"
    echo "   放好之后重跑本脚本即可（会跳过下载，仍会校验）。"
    exit 1
  fi
fi

echo "==> 校验 sha256"
ACTUAL=$(sha256sum "${CHART_FILE}" | cut -d' ' -f1)
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

# 判据必须解析渲染产物，不能靠 grep —— 第一版就是这么错的（2026-10-17 现场）：
#   · `grep -c '^kind: Deployment'` 把 replicas:0 的 Deployment 也算成常驻 → 误报"5 个"
#   · `grep 'argocd-dex-server'` 命中的是 TLS Secret 名 `argocd-dex-server-tls` → 误报"3 处 dex"
# 两个都是**假阳性**：会让正确的配置被拦下。假阴性（该拦没拦）更糟。
if ! python3 - "${WORK}/rendered.yaml" <<'PY'
import sys
import yaml

docs = [d for d in yaml.safe_load_all(open(sys.argv[1], encoding='utf-8')) if d]
wl = [d for d in docs if d['kind'] in ('Deployment', 'StatefulSet')]
run = [d for d in wl if (d['spec'].get('replicas') or 0) > 0]
off = sorted(d['metadata']['name'] for d in wl
             if 'dex' in d['metadata']['name'] or 'notification' in d['metadata']['name'])

print('   常驻工作负载 {} 个（期望 4）: {}'.format(
    len(run), ', '.join(d['metadata']['name'] for d in run)))
print('   被关掉的组件仍存在工作负载 {} 个（期望 0）{}'.format(len(off), off or ''))

ok = (len(run) == 4 and not off)
for d in run:
    lim = (d['spec']['template']['spec']['containers'][0].get('resources') or {}).get('limits')
    if not lim:
        print('   ⚠️ {} 没有 limits（不满足"失控时不连累邻居"）'.format(d['metadata']['name']))
        ok = False
sys.exit(0 if ok else 1)
PY
then
  echo "❌ 渲染结果与预期不符，停手检查 values.yaml"
  exit 1
fi

# ── 3.5 集群连通性预检（把"连不上"的问题挡在安装之前）────────────────
# 没有这一步，helm 会走到最后一步才报 "Kubernetes cluster unreachable"，
# 而那时 chart 已下完、渲染已过，看起来像"装到一半失败"，其实是**一个前置条件没满足**。
echo "==> 集群连通性预检"
printf '   KUBECONFIG = %s\n' "${KUBECONFIG}"
if [ ! -r "${KUBECONFIG}" ]; then
  echo "❌ 读不到 kubeconfig：${KUBECONFIG}"
  echo "   k3s 的 kubeconfig 通常在 /etc/rancher/k3s/k3s.yaml（mode 600，需 root）"
  echo "   可显式传入：KUBECONFIG=/path/to/k3s.yaml bash $0"
  exit 1
fi
if ! helm list -A >/dev/null 2>&1; then
  echo "❌ helm 连不上集群（KUBECONFIG=${KUBECONFIG}）"
  echo "   自查：KUBECONFIG=${KUBECONFIG} helm list -A       # 看具体报错"
  echo "         k3s kubectl get nodes                        # 对照，它自带 kubeconfig"
  echo "   常见原因：k3s 服务未运行 / 6443 被防火墙挡在**本机**之外 / kubeconfig 过期"
  exit 1
fi
echo "   ✅ 集群可达（k3s 内已有 release：$(helm list -A -q 2>/dev/null | tr '\n' ' ')）"

# ── 4. 安装/升级 ──────────────────────────────────────────────────
echo "==> helm upgrade --install"
helm upgrade --install argocd "argo-cd-${CHART_VER}.tgz" \
  -n "${NS}" --create-namespace \
  -f "${REPO}/k8s/argocd/values.yaml" \
  --wait --timeout 12m || {
    echo
    echo "❌ helm upgrade --install 失败。先看现状，别急着重跑："
    echo "   k3s kubectl -n ${NS} get pods"
    echo "   k3s kubectl -n ${NS} get events --sort-by=.lastTimestamp | tail -20"
    echo "   （--wait 超时多半是某个 Pod 还在拉镜像，重跑会让 helm 从头再来，反而更慢）"
    exit 1
  }

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
