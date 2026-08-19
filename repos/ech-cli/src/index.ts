// 引入commander：Node生态最主流的命令行参数解析库，用来实现cli命令、参数、选项
import { Command } from 'commander';

// 批量导入各个业务模块的命令注册函数
// 每个文件内部会给program对象注册一组子命令，比如登录、会话、Agent、知识库、工作流等
import { registerAuthCommands } from './commands/auth.js';                // 认证相关：登录、token管理
import { registerConversationCommands } from './commands/conversation.js'; // 会话管理
import { registerChatCommands } from './commands/chat.js';                 // 聊天交互
import { registerVisitorCommands } from './commands/visitor.js';           // 访客相关
import { registerAgentCommands } from './commands/agent.js';               // AI Agent操作
import { registerProviderCommands } from './commands/provider.js';         // LLM模型服务商
import { registerKnowledgeCommands } from './commands/knowledge.js';       // RAG知识库
import { registerWorkflowCommands } from './commands/workflow.js';         // Agent工作流
import { registerStaffCommands } from './commands/staff.js';               // 内部员工账号
import { registerPlatformCommands } from './commands/platform.js';         // 第三方平台(钉钉/企微等)
import { registerTagCommands } from './commands/tag.js';                   // 标签管理
import { registerSystemCommands } from './commands/system.js';             // 系统配置、运维命令

// 实例化CLI主对象，所有命令都挂载到这个program
const program = new Command();

program
  .name('tgo')                          // cli工具名字，终端执行：tgo
  .description('TGO CLI - AI Agent customer service operations tool') // help帮助文本描述
  .version('0.1.0')                     // tgo --version 展示版本号

  // ---------------- 全局选项：所有子命令都可以共用这些参数 ----------------
  .option('-s, --server <url>', 'API server URL')    // 指定后端API地址，切换开发/生产环境
  .option('-t, --token <token>', 'Auth token')       // 接口鉴权token，代替登录，直接调用后端接口
  .option('-o, --output <format>', 'Output format: json, table, compact', 'json') 
  // 输出格式，默认json；可以表格/精简文本打印结果，方便脚本解析或者人看
  .option('-v, --verbose', 'Verbose output');        // 详细日志，排错用，打印请求、报错详情


// 注册全部业务命令组
// registerXxxCommands(program) 内部逻辑：给program添加子命令，例如 tgo agent list、tgo knowledge create
registerAuthCommands(program);
registerConversationCommands(program);
registerChatCommands(program);
registerVisitorCommands(program);
registerAgentCommands(program);
registerProviderCommands(program);
registerKnowledgeCommands(program);
registerWorkflowCommands(program);
registerStaffCommands(program);
registerPlatformCommands(program);
registerTagCommands(program);
registerSystemCommands(program);


// ========== MCP 服务专属命令 ==========
// tgo mcp serve
program
  .command('mcp')                    // 一级子命令 tgo mcp
  .description('MCP Server commands')
  .command('serve')                  // 二级子命令 tgo mcp serve
  .description('Start MCP Server (stdio transport)') // stdio标准输入输出传输，MCP本地进程通信
  .action(async () => {
    // 动态延迟导入：只有执行这条命令才加载mcp/server.js，不跑mcp的时候不会加载该模块，减少启动开销
    const { startMcpServer } = await import('./mcp/server.js');
    await startMcpServer();
  });

// 解析终端传入的命令行参数，整个cli开始运行
program.parse();