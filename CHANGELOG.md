# 更新日志

## v2026.05.12

- 修复 MySQL 使用 `sha256_password` 或 `caching_sha2_password` 认证方式时，因缺少 `cryptography` 依赖导致连接测试失败的问题。

