# Proposal — 基于 JWT 的用户认证系统

## 为什么做
现有系统缺乏统一的用户认证能力，前端与后端之间无法建立可信的身份上下文。需要一套基于 JWT 的无状态认证体系，支撑登录、注册、刷新 Token 三个核心接口。

## 现状问题
- 无用户账号体系，无登录态保持
- 各接口各自校验，缺乏统一鉴权入口
- 不存在可刷新的短时凭证机制

## 目标
1. 实现 `POST /auth/register`：用户注册，密码哈希存储
2. 实现 `POST /auth/login`：账号密码登录，签发 access_token 与 refresh_token
3. 实现 `POST /auth/refresh`：凭 refresh_token 换取新的 access_token
4. 统一的 JWT 签发/验证工具与密钥管理

## 影响范围
- 新增 `auth` 模块（控制器、服务、仓库、JWT 工具）
- 新增数据表：`users`、`refresh_tokens`
- 新增全局异常处理与鉴权中间件

## 不包含什么
- 第三方 OAuth / SSO 登录
- 多因素认证 (MFA)
- 密码找回 / 重置流程
- 角色/权限模型（RBAC） — 仅做身份认证（AuthN）

---
