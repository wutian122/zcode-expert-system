# Design — 基于 JWT 的用户认证系统

## 架构概览
RESTful 风格的无状态认证服务，访问入口为三个 HTTP 接口，JWT 为无状态凭证，Refresh Token 存储于数据库并按需吊销。

## 模块职责
| 模块 | 职责 |
|------|------|
| `AuthController` | 接收 `/auth/register`、`/auth/login`、`/auth/refresh` 请求，做入参校验，返回统一响应 |
| `AuthService` | 业务编排：密码校验、JWT 签发/验证、Refresh Token 生成与吊销 |
| `UserRepository` | `users` 表 CRUD：按用户名/邮箱查询、插入新用户 |
| `RefreshTokenRepository` | `refresh_tokens` 表 CRUD：插入、按 token 查询、标记已使用/吊销 |
| `JwtUtil` | JWT 签名（HS256）、验证、解析载荷、过期时间控制 |
| `PasswordUtil` | PBKDF2-HMAC-SHA256（100,000 迭代 + 16 字节随机盐）哈希与恒定时间校验；未引入 bcrypt，保持零新增依赖 |
| `AuthMiddleware` | 全局鉴权中间件（Access Token 校验，保护业务接口） |

## 数据结构
**users**
- id (PK, UUID)
- username (UNIQUE, NOT NULL)
- email (UNIQUE, NOT NULL)
- password_hash (NOT NULL)
- created_at

**refresh_tokens**
- id (PK, UUID)
- user_id (FK → users.id)
- token_hash (UNIQUE, NOT NULL) — 存 sha256(令牌明文)，不存明文
- expires_at (NOT NULL) — ISO 8601 字符串（UTC），写入与解析均为 ISO 串
- revoked_at (NULLABLE) — ISO 8601 字符串（UTC）
- created_at

## API
- `POST /auth/register` body `{username, email, password}` → 201 `{userId, username}`
- `POST /auth/login` body `{usernameOrEmail, password}` → 200 `{accessToken, refreshToken, expiresIn}`
- `POST /auth/refresh` body `{refreshToken}` → 200 `{accessToken, refreshToken, expiresIn}`（旋转：旧 refresh token 吊销，签发新对）

## 安全与兼容
- 密码使用 PBKDF2-HMAC-SHA256（100,000 迭代，16 字节随机盐）哈希，校验走 `hmac.compare_digest`；明文不落盘、不回显
- Access Token 短时效（建议 15 分钟），携带 `sub`（用户 ID）、`iat`、`exp`
- Refresh Token 长时效（建议 7 天），存哈希，单点使用后旋转
- 密钥通过环境变量 `JWT_SECRET` 注入，不硬编码
- 失败返回 400/401，统一错误码，不泄露用户是否存在

## 实现决策（缺陷修复轮 R1/R2/R3 落地，2026-11-22）

- **R1 — refresh 过期时间解析**：`expires_at` 在 `refresh_tokens` 表中是 ISO 8601 字符串
  （login 写入时 `datetime.fromtimestamp(..., tz=utc).isoformat()`）。旧实现用 `float(expires_at)`
  解析，对 ISO 串必然抛 `ValueError`，导致刷新 100% 崩溃。
  决策：改用 `datetime.fromisoformat` 解析，并把 `ValueError/TypeError` 归一化为
  `InvalidRefreshTokenError`（拒绝刷新），让格式异常成为 401 语义而非 500 泄漏。
  时间比较统一用 `datetime.timestamp()` 与 `time.time()` 比对，吊销时间写 UTC ISO 串，与 `expires_at` 同基线。

- **R2 — refresh token 熵源与存储**：旧实现 `sha256(user_id:time_ns)` 派生，空间小、可预测。
  决策：令牌明文改由 `secrets.token_urlsafe(32)` 生成（约 256 位熵）；
  **入库与查询前统一经 `_hash_token()`（sha256 hex）**——数据库列只存哈希，
  即使库泄露也无法直接重放令牌；查询时对客户端回传的明文先哈希再用 `token_hash` 命中。

- **R3 — JWT header 白名单校验**：旧 `verify()` 只验签名与过期，不校验 header，
  存在算法混淆（`alg=none` / 换 `typ`）风险。
  决策：验签**之前**先解析 header，白名单校验 `alg == "HS256"` 且 `typ == "JWT"`；
  header 不可解析或字段不符一律抛 `TokenInvalidError`，不进入签名与过期检查。

## 未实现项与影响面
- Task 5（AuthController 三接口 + 全局异常处理）尚未实现：`src/auth` 无 controller、
  无 `AuthMiddleware`，HTTP 状态码与统一错误响应体待落地。
- 因此上述设计的 201/200/401/409 响应契约目前只有服务层异常类型与错误码字符串可验证；
  端到端 HTTP 契约的验证随 Task 5 补齐。

## 风险
- Refresh Token 泄露可导致账号接管，缓解：旋转 + 吊销列表 + 短时 access token
- JWT 无法在过期前主动吊销，缓解：缩短 access token 生命周期

---
