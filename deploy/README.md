# deploy

部署相关的一切：Docker Compose、镜像定义、初始化 SQL、运维脚本。

**当前状态**：占位。按排期表 **A02** 才在这里落地 `docker-compose.yml`（PostgreSQL 16 + 应用）
与镜像定义，届时补齐：

```
deploy/
├── docker-compose.yml        postgres:16 + backend 服务
├── backend.Dockerfile
└── postgres/init/            初始化 SQL（建库、建扩展）
```

`make up`（Makefile）/ `make docker-up`（make.ps1）会指向这里的 compose 文件。
在那之前这些目标会因为文件不存在而失败——这是**故意的**，A02 会把它们补上。
