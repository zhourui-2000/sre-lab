# 防火墙持久配置漂移：一条无主规则游离 28 天

2026-10-14（漂移产生于 2026-09-16 18:29:41）。`trusted` 区多出一条 IaC 之外的 `192.168.0.0/16`：无功能影响，重建时会静默丢失，真源不止一个。

## 判据

用 firewalld 自带的双目录基线，不需要白名单：

```text
/usr/lib/firewalld/zones/*.xml   RPM 出厂定义，本地改动不写这里  ← 天然基线
/etc/firewalld/zones/*.xml       firewalld 只在本地有改动时生成

全部本地改动 = 当前态 − 出厂态
无主改动     = 全部本地改动 − IaC 声明
```

逐条 diff：

```text
--- public  ---  差异 3 条 = IaC 声明的 3 条          ✅
--- trusted ---  差异 2 条，IaC 只声明 1 条           ❌
                 > <source address="172.16.0.0/12"/>   ← IaC 有
                 > <source address="192.168.0.0/16"/>  ← 漂移
--- docker ---   /usr/lib 无对应文件，docker 运行时创建，不算漂移
```

不用白名单：`public` 出厂自带 `ssh` / `dhcpv6-client` / `cockpit`，写死会误报。

## 根因

机制层：`security` 任务（`ansible/roles/security/tasks/main.yml`）先 `--query-*`，不在才 `--add-*`，从不删除、从不重置。

| 服务器上的动作 | playbook 反应 | 症状 |
|---|---|---|
| 加一条新规则 | 不撤销 | `changed=0`、无警告，失败只在重建那天暴露 |
| 删 IaC 里已有条目 | 下次跑加回来 | "我改的东西自己变回来了" |
| 只改 runtime、不带 `--permanent` | — | `reload` 或重启即消失，假象 |

判据是"我声明的都在"，不是"实际的都归我管"；危害形状 `exit code = 0` 无警告。

过程层：09-16 手工敲两条，回填一条（见 [09-16 记录](2026-09-16-firewalld-blocks-scrape.md)）。

```text
/root/.bash_history:178,180   firewall-cmd --permanent --zone=trusted --add-source=172.16.0.0/12
/root/.bash_history:181       firewall-cmd --permanent --zone=trusted --add-source=192.168.0.0/16
/root/.bash_history:182       firewall-cmd --reload
```

改动前 `trusted.xml.old` 里只有 `172.16.0.0/12`。

## 修复

```sh
firewall-cmd --permanent --zone=trusted --remove-source=192.168.0.0/16
firewall-cmd --reload
```

再把 k3s 需要的 `10.42.0.0/16` / `10.43.0.0/16` 补进 IaC。顺序：先改 IaC 再让 playbook 建，首次 `changed=2` 才证明"从无到有"；先手工加只会 `changed=0`，证明不了 IaC 能重建。

## 判据

`scripts/check-fw-drift.py`（退出码 `0` 干净 / `1` 有漂移或缺失 / `2` 工具前提失效）：

| 时点 | 结果 |
|---|---|
| 修复前 | `❌ 漂移 1 条`：`trusted source 192.168.0.0/16`，exit=1 |
| 删除后 | `✅ 完全一致（无漂移、无缺失）`，exit=0 |
| k3s 规则入 IaC 并 apply | `IaC 声明 6 条` == `本地改动 6 条`，exit=0 |

失败分支也验过：假仓库报出 2 条缺失，坏路径 exit=2。

`/etc/firewalld/zones/*.xml.old` 的 mtime 正是 `2026-09-16 18:29:41`，可给非 IaC 改动定时。

## 遗留

`6443/tcp` 刻意不开（单节点无外部节点访问 apiserver）。可选加固：把 `cni0` / `flannel.1` 接口绑进 trusted 区，更精确，代价是"接口必须先存在"的启动顺序依赖，留作 Week 3-4。

风险看消费方：这条规则 conntrack 实测 0 条流量，丢了是审计问题；k3s 两条网段规则丢了是功能事故（[methodology ⑮](../methodology.md)、[baseline](../baseline.md)）。
