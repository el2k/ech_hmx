// 导入commander命令对象类型
import { Command } from 'commander';
// TgoClient：封装好的HTTP请求客户端，内部封装请求头、错误处理，专门调用TGO后端API
import { TgoClient } from '../client.js';
// loadConfig读取本地配置；resolveOutput解析输出格式；resolveServer解析服务地址；updateConfig写入本地配置文件
import { loadConfig, resolveOutput, resolveServer, updateConfig } from '../config.js';
// printError打印错误；printResult按json/table/compact格式输出结果到终端
import { printError, printResult } from '../output.js';

/**
 * 注册 auth 认证组命令，挂载到上层program对象
 * 使用：tgo auth login / tgo auth logout / tgo auth whoami
 * @param parent 顶层commander实例
 */
/*tgo auth login -u admin -p xxx
        ↓
commander解析命令参数
        ↓
new TgoClient({server:"http://127.0.0.1:8000"})
        ↓
client.postForm("/v1/staff/login", payload)
        ↓
【TgoClient内部】拼接完整URL、组装请求头、执行fetch网络请求
        ↓
发送HTTP请求 → FastAPI后端服务
        ↓
后端返回 {"access_token":"xxx", ...}
        ↓
拿到result，保存token到本地配置文件 updateConfig */
export function registerAuthCommands(parent: Command): void {
  // 创建一级子命令：tgo auth
  const auth = parent.command('auth').description('Authentication commands');

  // ---------------- tgo auth login 登录命令 ----------------
  auth
    .command('login')
    .description('Login and save token')
    // 必填参数：用户名、密码，执行命令必须带上 -u -p
    .requiredOption('-u, --user <username>', 'Username or email')
    .requiredOption('-p, --pass <password>', 'Password')
    .action(async (opts, cmd) => {
      // 获取顶层全局选项（--server / --token / --output这些）
      const globals = cmd.parent!.parent!.opts();
      // 解析输出格式 json / table / compact
      const format = resolveOutput(globals.output);
      try {
        // 解析后端服务地址，优先级：命令行--server > 本地配置文件 >环境变量
        const server = resolveServer(globals.server);
        if (!server) {
          throw new Error('Server URL required. Use --server or TGO_SERVER env var.');
        }
        // 创建http客户端实例，指定后端地址
        const client = new TgoClient({ server });
        // 调用后端登录接口 POST /v1/staff/login
        // postForm：发送form‑urlencoded表单请求（OAuth2 password模式）
        const result = await client.postForm<{
          access_token: string;
          token_type: string;
          staff: Record<string, unknown>;
        }>('/v1/staff/login', {
          username: opts.user,
          password: opts.pass,
          grant_type: 'password', // OAuth2密码授权模式
        });

        // ✍️关键：登录成功，把server地址 + access_token写入本地配置文件保存
        // 后续执行其他tgo命令不用每次传 -t token
        updateConfig({ server, token: result.access_token });

        // 打印登录成功结果，按format格式输出
        printResult({
          success: true,
          message: 'Logged in successfully',
          staff: result.staff,
        }, format);
      } catch (err) {
        // 捕获网络错误、账号密码错误，统一格式化打印错误
        printError(err, format);
      }
    });

  // ---------------- tgo auth logout 登出 ----------------
  auth
    .command('logout')
    .description('Clear saved token')
    .action((_opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      // 将配置里token置为undefined，清空本地保存的令牌
      updateConfig({ token: undefined });
      printResult({ success: true, message: 'Logged out' }, format);
    });

  // ---------------- tgo auth whoami 查询当前登录用户 ----------------
  auth
    .command('whoami')
    .description('Show current login info')
    .action(async (_opts, cmd) => {
      const globals = cmd.parent!.parent!.opts();
      const format = resolveOutput(globals.output);
      try {
        const client = new TgoClient({
          server: resolveServer(globals.server),
          token: globals.token, // 使用命令行传入或者本地配置的token
        });
        // 请求后端接口获取当前登录员工信息 /v1/staff/me
        const result = await client.get('/v1/staff/me');
        printResult(result, format);
      } catch (err) {
        printError(err, format);
      }
    });
}

// =====================================================
// 【MCP独立导出函数】
// 不依赖commander，不操作终端输出；纯粹业务逻辑，供MCP服务调用
// MCP工具调用时，不会走终端命令解析，直接调用这些js函数
// =====================================================

/** MCP调用：执行登录逻辑 */
export async function authLogin(server: string, username: string, password: string): Promise<unknown> {
  const client = new TgoClient({ server });
  const result = await client.postForm<{
    access_token: string;
    token_type: string;
    staff: Record<string, unknown>;
  }>('/v1/staff/login', {
    username,
    password,
    grant_type: 'password',
  });
  updateConfig({ server, token: result.access_token });
  return { success: true, message: 'Logged in successfully', staff: result.staff };
}

/** MCP调用：获取当前用户信息 */
export async function authWhoami(clientOpts?: { server?: string; token?: string }): Promise<unknown> {
  const client = new TgoClient(clientOpts);
  return client.get('/v1/staff/me');
}

/** MCP调用：登出 */
export function authLogout(): unknown {
  updateConfig({ token: undefined });
  return { success: true, message: 'Logged out' };
}