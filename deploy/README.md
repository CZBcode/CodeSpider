# Linux 服务器部署

以 `/opt/codespider` 存放代码、`codespider` 系统用户运行服务，复制
`codespider.service` 到 `/etc/systemd/system/` 后启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now codespider
sudo systemctl status codespider
```

服务监听 `0.0.0.0:8787`。数据和默认新建项目位于
`/var/lib/codespider/.codespider`。日志使用 `journalctl -u codespider` 查看。

当前 Web 控制台包含本地命令执行能力，公开部署时应通过云安全组或防火墙限制
8787 来源地址，并优先放在带认证的反向代理后面。
