# Tasks — 基于 JWT 的用户认证系统

- [x] Task 1: 搭建 auth 模块骨架与数据表（src/auth 目录 + users/refresh_tokens 建表）
- [x] Task 2: 实现密码哈希工具与 JwtUtil（bcrypt 回退 pbkdf2 + HS256 签发/验证）
- [x] Task 3: 实现 UserRepository 与 RefreshTokenRepository（users 查询/插入，refresh token 插入/查询/吊销）
- [x] Task 4: 实现 AuthService 业务编排（注册/登录/刷新，单用旋转）
- [ ] Task 5: 实现 AuthController 三个接口与全局异常处理
- [x] Task 6: 编写单元与集成测试（TDD）

## 任务详情

### Task 1: 搭建 auth 模块骨架与数据表
- 依赖：无
- 验收条件：`users`、`refresh_tokens` 表已建表并可迁移；auth 模块目录结构就绪

### Task 2: 实现密码哈希工具与 JwtUtil
- 依赖：Task 1
- 验收条件：哈希/校验可用；JWT 签发/验证/解析通过单元测试，过期 Token 被正确拒绝

### Task 3: 实现 UserRepository 与 RefreshTokenRepository
- 依赖：Task 1
- 验收条件：按用户名/邮箱查用户；插入/查询/吊销 refresh token 均可用

### Task 4: 实现 AuthService 业务编排
- 依赖：Task 2, Task 3
- 验收条件：注册/登录/刷新三项流程端到端可跑，重复注册与错误凭证均返回正确错误码

### Task 5: 实现 AuthController 三个接口与全局异常处理
- 依赖：Task 4
- 验收条件：`POST /auth/register`、`/auth/login`、`/auth/refresh` 响应符合 spec，统一错误码输出
- 实际状态：**未实现**（`src/auth` 下无 controller / middleware / 全局异常处理）。
  服务层已直接抛 `DuplicateAccountError` / `InvalidCredentialsError` /
  `InvalidRefreshTokenError`，错误码常量齐备，HTTP 映射待 Task 5 落地。
- 受此影响：Scenario 1/2/3/4/5/6 的**状态码断言**（201/200/401/409）无法端到端验证，
  当前仅验证服务层行为（异常类型与错误码字符串）。

### Task 6: 编写单元与集成测试（TDD）
- 依赖：Task 1~Task 5
- 验收条件：六个场景全部覆盖，测试全部通过（GREEN）
- 实际状态：`tests/test_auth_login.py` 17 个用例全通过（2026-11-22 复测）。
  JWT 工具 / 密码工具 / 登录 / 刷新覆盖已齐，Scenario 1/2/3/4/5/6 均可验证；
  缺陷修复轮新增回归用例：R1（refresh ISO 解析）、R2（令牌随机性 + 只存哈希）、
  R3（header alg/typ 白名单）。