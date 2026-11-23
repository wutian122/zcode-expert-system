# Spec — User Authentication

> 实现口径（2026-11-22 与代码核对）：密码哈希为 **PBKDF2-HMAC-SHA256 / 100,000 迭代 + 16 字节随机盐**
> （`src/auth/password_util.py`；bcrypt 未引入以保持零新增依赖），存储形态为 `base64(salt + dk)`，
> 校验用 `hmac.compare_digest` 恒定时间比较。六个 Scenario 中服务层行为已由
> `tests/test_auth_login.py`（17 用例）覆盖；HTTP 层（状态码、全局异常处理）随 Task 5 落地后才可端到端验证。

## Requirement: User Authentication
用户可通过账号密码进行注册、登录，并使用 Refresh Token 获取新的 Access Token。

### Scenario: Successful Registration
- WHEN 用户提交未注册的用户名/邮箱与符合强度要求的密码
- THEN 系统创建用户账号，密码以哈希形式存储（PBKDF2-HMAC-SHA256，含随机盐，明文不落库）
- AND 返回 201 与用户标识

### Scenario: Registration — Duplicate Account
- WHEN 用户提交已存在的用户名或邮箱
- THEN 系统拒绝注册
- AND 返回 409 与错误码 `DUPLICATE_ACCOUNT`

### Scenario: Successful Login
- WHEN 用户提交正确的账号与密码
- THEN 系统验证身份
- AND 返回有效的 access_token（HS256，header 含 `alg=HS256`、`typ=JWT`）与 refresh_token
- AND refresh_token 由 `secrets.token_urlsafe(32)` 生成（密码学随机，不可由用户 ID/时间推导），
  数据库只存其 sha256 哈希

### Scenario: Login — Invalid Credentials
- WHEN 用户提交错误的账号或密码
- THEN 系统拒绝登录
- AND 返回 401 与错误码 `INVALID_CREDENTIALS`（不区分是账号错还是密码错）

### Scenario: Successful Token Refresh
- WHEN 客户端持有未过期、未吊销的 refresh_token
- THEN 系统签发新的 access_token 与新的 refresh_token
- AND 旧 refresh_token 被标记为已使用/吊销
- AND `expires_at` 按 ISO 8601 字符串解析（`datetime.fromisoformat`），过期判定基于 UTC 时基

### Scenario: Token Refresh — Expired/Revoked
- WHEN refresh_token 已过期或已吊销
- THEN 系统拒绝刷新
- AND 返回 401 与错误码 `INVALID_REFRESH_TOKEN`
- AND `expires_at` 解析失败（格式异常）同样归一化为 `INVALID_REFRESH_TOKEN`，不得泄漏为 500

### Scenario: Access Token — Invalid Header
- WHEN access_token 的 header 无法解析，或 `alg` 非 HS256、`typ` 非 JWT
- THEN 系统在验签**之前**即拒绝（header 白名单校验）
- AND 抛出 `TokenInvalidError`（不进入签名与过期检查，防算法混淆攻击）

---
