场所网页部署样例（systemd + nginx）。

完整步骤见仓库 docs/场所网页部署.md。
书面口径见仓库 docs/双端交付口径.md。

本机预览（开发机）：
  python -m electrical_krow site --port 18767
  浏览器打开 http://127.0.0.1:18767/ ，应显示「场所网页」。

本目录：
  config.ini                 delivery=site，应用绑 127.0.0.1
  electrical-krow.service    systemd 单元
  nginx.conf.example         内网 HTTPS 反代
  docker-compose.yml         可选容器（仍须宿主机 nginx）

不要把 18765 映射到公网。规格书落 ELECTRICAL_KROW_DATA，识别打现场 Krow Server。
