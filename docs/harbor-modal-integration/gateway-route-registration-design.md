# 真实 Gateway 动态端口登记：最小可复建控制面

状态：controller 与训练侧注册客户端已实现 CPU 合同测试；尚待真实隧道与训练验收。目标为当前单 Gateway、单 Worker 的真实 M2 执行，不修改 VERL 或 run_uvicorn，不人工修改运行中的 YAML。

## 核心决定

新增 Mac 所有的有界 run controller。训练端的可信 runner 在 Task 构造之前，向 controller 登记从真实 SessionHandle 得到的 Gateway host/port。Controller 只允许补齐本次 run 的动态端口；task、release、预算、模型、允许的 Gateway 节点 IP、SSH 目的机器和本地转发端口均由操作员事先冻结。Controller 不是从 JobRequest 生成批准策略。

HarborWorker 仍以完整且不可变的 RequestPolicy 启动。未登记前不启动 worker；第一次有效登记时创建 SSH 模型隧道、落盘完整 policy、启动已有 worker 服务。后续相同 host/port 登记幂等返回原 policy；同 run 换端口/节点直接拒绝，要求关闭本 run 后新建 run。

## 拓扑

```text
Mac run controller（loopback control port；独立 registration token）
  ├─ 预启动：Mac-owned SSH → RunPod
  │     -R remote-control-port:127.0.0.1:mac-control-port
  │     -R remote-worker-port:127.0.0.1:mac-worker-port
  └─ 第一次有效登记后：
        -L mac-model-port:allowed-gateway-node:actual-gateway-port
        effective-policy.json → 现有 harbor_worker.py

RunPod trusted run_task(SessionHandle)
  → remote-control-port 登记真实 origin
  ← 完整 policy + run/spec/policy hash
  → HarborDshTask（原始Session URL +完整policy）
  → remote-worker-port → Mac Worker → Harbor容器
                                    → host.docker.internal:mac-model-port
                                    → 真实Gateway的原样session path
```

SSH 密钥与 known_hosts 全程留在 Mac。注册凭据仅在训练主控/runner进程；Worker job token 与注册 token 分离，两者都不注入学生容器。模型隧道只转 TCP，不改写 HTTP session path。

## 启动合同：OperatorRunSpec

操作员在启动前固定并产生单一私有 run spec：

- run_id、controller_id、绝对总截止时间、固定 worker_id。
- task_dir 及 task_refs、instruction身份、完整 DSH release/image、全部资源上限。
- allowed_gateway_host（首轮仅一个确定节点 IP）、model_name、tunnel_alias。
- SSH host/port/user、已验证 known_hosts、私钥路径、本地模型端口/worker端口/control端口及远端control/worker端口。
- registration token file、worker token file、私有run目录。

Controller独立读取并冻结此文件；训练侧配置由同一run spec生成，记录相同spec SHA256，不接受dataset生成或修改run spec。

现有 Task YAML 的 `policy` 先保存上述固定字段，**有意不包含gateway_port**，不是填假端口。TaskConfigResolver当前只检查保护字段`policy`存在，尚不解析其内部RequestPolicy；因此可在resolve之后、get_task之前补齐动态端口而无需更改resolver或TaskConfig合同。只有完整有效policy才能构造HarborDshTask。

## HTTP 与可信 runner API

### Controller：POST /v1/runs/{run_id}/gateway

认证：仅registration token，不能用job token调用。

请求：`{"gateway_host": "已固定节点IP", "gateway_port": 真实SessionHandle端口, "run_spec_sha256": "sha256:..."}`。

请求不接收task/release/budget/model/SSH目标/本地转发端口/任意命令。Controller核run_id、spec hash、deadline、host完全匹配，并校验端口范围。加单一注册锁避免多个candidate同时启动隧道/worker。

成功响应：`run_id/controller_id/run_spec_sha256/policy_sha256/policy/registered_at_unix`。policy由controller冻结spec和允许的端口生成；落盘原始登记与resolved policy并fsync。重复相同登记返回同一回执；不同登记409。Controller重启默认拒绝自动恢复运行，要求核对原子状态和旧SSH/Worker终止记录后开启新run。

### Runner：ensure_harbor_route(session, operator_config) -> RequestPolicy

新helper仅由run_task的可信代码调用：

1. 从session.base_url解析host/port；确认session_id、_runner_context.gateway_session_id、精确URL path一致。
2. 读操作员runner参数中的controller URL/token/spec hash，而非tools_kwargs.task字段。
3. 通过已建立控制隧道登记。相同run重复调用可直接依赖controller幂等性，不先加分布式缓存。
4. 核响应run/controller/spec身份；完整policy去掉gateway_port之后，必须逐字段等于原操作员policy模板，且port等于当前SessionHandle。
5. 把完整policy、session.base_url、deepcopy(_runner_context)覆盖到resolved Task配置，再get_task。任何失败不创建JobRequest，不启动学生。

入口建议用run_task新显式参数`harbor_route_registration`（来自框架runner配置），包含controller_url、token_file、run_spec_sha256、controller_id和短deadline。不要把它加到dataset task配置。现有已固定完整policy仍可沿用静态模式。

这里的“真实SessionHandle”来源是可信Framework调用链，而不是HTTP字段自身的密码学证明；controller信任独立注册凭据持有者。学生与job提交凭据不具备注册权限。

## Mac生命周期与故障处理

1. `harbor_run_controller.py --run-spec ...`读取冻结spec，绑定loopback控制端口，建立已有两条-R控制转发；worker尚未监听。
2. 首次登记先排他保留registration intent；启动独立ssh子进程`-N -L`，使用BatchMode/ExitOnForwardFailure/固定known_hosts。所有参数用argv传递。
3. 独立确认转发进程存活和TCP通路；不把端口监听当作模型采样证明。然后落盘effective-policy并以既有CLI启动worker。
4. 通过已认证HTTP状态探针确认worker就绪（可给已有worker添加不含敏感信息的GET /v1/health）；全部成功后才返回登记成功。
5. 隧道/worker启动失败：停止本次已启动子进程、保存失败；默认该run不自动重新绑定/重试。
6. 总截止时间到或controller关闭：先停止接收登记/新job，向独立worker进程发送SIGINT，让既有asyncio.run取消main并进入finally中的worker.close，等待正在执行的取消清理；保存unconfirmed状态，不伪造资源清理；之后终止模型/控制SSH子进程并wait回收。若有界清理宽限期耗尽，再升级停止并明确保留unconfirmed，不声称Docker已回收。
7. 运行中模型隧道或worker异常退出：标记run failed，拒绝新登记/任务，保留身份/日志；不自动换端口接回新Gateway。

## 最小文件变更与验收

- 新增`deployment/services/harbor_run_controller.py`：spec、登记锁、子进程生命周期及HTTP入口。
- 新增`uni_agent/tasks/harbor_dsh/registration.py`：纯控制客户端、响应固定字段验证；不创建JobRequest。
- 修改`uni_agent/framework/task_runner.py`：Harbor resolve后、get_task前调用helper；保留静态policy路径。
- 必要小改`worker_http.py`：只读认证health，不修改任务批准逻辑。
- 添加对应CPU测试：错误host/spec/run/token拒绝；相同登记一次SSH/worker启动；并发登记；异端口拒绝；启动中失败逆序清理；deadline关闭；响应偷改release/budget/task/model拒绝；缺真实session不登记；未登记不执行Task。
- 真实验收依次记录：controller注册回执→SSH/worker生命周期→一个真实Gateway学生请求→Task/receipt→训练准入与optimizer消费。控制探针不算训练通过。

首轮强制单Gateway per run。增加多Gateway时需按origin建立独立worker/tunnel并明确路由所有权，不在本轮将冻结policy改成任意端口白名单。


## 训练侧实现合同与验收（2026-09-08）

`run_task` 新显式 operator kwargs：

```yaml
harbor_route_registration:
  controller_url: http://127.0.0.1:47200
  token_file: /private/run-secrets/registration-token
  registration_root: /private/run-evidence/registrations
  controller_id: controller-1
  run_spec_sha256: sha256:<真实规范化RunSpec摘要>
  timeout_seconds: 30.0
```

这是参数形状示例，不是可直接执行配置。token_file 必须在仓库之外、本人所有的私有 regular 单链接文件；值只进入 Authorization，不写证据。helper严格接受 `SessionHandle` 实例，核对真实 Framework context 与 session path。注册请求精确三个字段；响应除 policy.gateway_port 之外必须与冻结模板、run/controller/spec/hash 相符。controller_url只接受明确IP的loopback HTTP origin，不跟随redirect，不读环境proxy，不自动解压；JSON上限64KiB；整个注册及落盘阶段超时最多60秒，默认30秒。

成功登记保存在 `registration_root/<run_id>/registration.json`（0600，目录0700）。用文件锁协调多个进程，临时文件 fsync 后原子发布；相同响应幂等，不同响应禁止覆盖。暂不缓存远端检查：每次 session 仍请求 controller，确保它拒绝已停止或换端口的run。注册失败或响应丢失不自动换run/端口，也不宣称远端资源已清理。

静态 FQN：`uni_agent.tasks.harbor_dsh.registration.validate_registered_trajectories`。传 `trajectory_postprocessor_pass_context=true`；operator kwargs为 `artifact_root, run_id, worker_id, task_ref, instruction, policy_template, registration_root, controller_id, run_spec_sha256`。`policy_template` 有意没有gateway_port；wrapper只从独立登记文件加载port，再调用原完整policy audit。Task receipt无法选择端口或controller。原 `trajectory_audit.validate_trajectories` 保留，适用于已冻结完整policy的静态路径。

已验证：24个注册客户端/runner/wrapper测试；registration + 两组runner + Harbor audit + controller组合116 passed（4.61秒）；三处代码Ruff check/format通过。包含真实aiohttp与controller实现的schema/hash合同、并发幂等、冻结字段篡改、注册凭据与Session输入拒绝、redirect不跟随、响应字节/时间限制、实际Task receipt经动态policy wrapper准入。SSH/worker启动工厂使用fake；不算真实隧道、模型或GPU训练验收。
