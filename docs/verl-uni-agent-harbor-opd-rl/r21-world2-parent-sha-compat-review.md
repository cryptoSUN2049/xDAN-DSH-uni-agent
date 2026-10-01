# R21 复合审计父spec SHA表示合同审查

## 当前真实问题

本轮r20f已原生exit0/C5，四唯一TQ消费、policy4、四session token、双rank LoRA/base/optimizer、原生W&B finished和Prom/Tempo均有当前实物PASS。既有world2汇总工具33cd6593真实运行输出仍为FAIL，错误为`Parent source/spec identity malformed`。失败报告SHA871130d649604bc998e1b745169a3d64cc27e7be2ec3063bb5fd98efbfc379a1已保留，不覆盖或改判。

实际父manifest40f25db06843bc9400f7f4fbe82eea46e7dcae8fffa9c5d383cf1ded40bb1270中的`run_spec_sha256`为裸64字符5951ccbe2ab4c29705bed8655a949efafa598c16cd26670c2791b0544e6e1e33。其source commit为4dbd87ad4f6123f99a1f715a6637322a44cff6a5。当前operator的`seal_parent`也明确要求裸64字符；旧汇总工具的`bind_parent_checkpoint`只接受`sha256:`前缀形式。这是同一哈希值表示合同不兼容，尚未触及后续实际检查。

## 最小建议与独立实现边界

保留原父manifest、所有checkpoint、生产runtime99ac、旧冻结审计33cd和失败报告字节。独立新审计版本仅对父spec身份接受严格两种表示：裸64个小写十六进制字符，或`sha256:`加64个小写十六进制字符。保留原字段表示，不重写输入、不注入私有shim。

```mermaid
flowchart LR
  P[原父manifest40f / 裸spec SHA] --> I[新审计严格格式校验]
  I --> H[原manifest SHA / 每个父文件完整hash]
  H --> B[当前四TQ / policy4 / 有限有差异reward]
  B --> D[原生C4至C5两rank LoRA / base / optim]
  D --> G[正负advantage / 非零grad / 当前run与spec]
  G --> O[新独立报告 / 旧FAIL保留]
```

不得改当前expected_spec合同（仍绑定launch的`sha256:06d4…`），不得去掉父manifest40f、两个world2/FSDP1、完整原文件SHA或任何有效更新门。checkpoint比较仍不冒充原生restore或能力提升。

## 拟改文件与验证合同

- 新增`docs/verl-uni-agent-harbor-opd-rl/mimo_world2_acceptance_r21.py`：独立离线审计版本，仅父spec格式正则与旧33cd不同；旧本地/云端33cd都不改，当前训练生产runtime不改。
- 新增独立CPU回归：真实`bind_parent_checkpoint`完整cross-run fixture（当前bare seal、既有prefixed seal均过），复用既有严格回归，不能只测试重复的正则。
- 负例：63/65字符、非法prefix、大写/非hex、换行、错source commit、错expected父manifest SHA、错step/world/FSDP、文件SHA变化仍拒绝。
- 云CPU跑既有回归和新增用例；明确新字节tests/coverage与source SHA，完整Ruff/Git审查后新独立cloud audit freeze。
- 真正再次执行当前world2审计，输入仍为同一实际C4父40f、当前launch e28f、batch c7b、delta9412、currentconsole；使用新O_EXCL输出，不复制旧PASS或合成参数。

## 当前交接

同组独立只读审查已确认表示合同缺口与最窄方案。为完成已授权本轮真实验收，prep正在新增独立离线工具与云CPU回归；r20_operator在测试通过后对同一实物执行新独立复合重审。不修改旧冻结审计、训练源码或父证据，不Git/push、不GPU，不能称旧33cd报告已通过。所有新工具/测试字节与实际结果须分别记录，未提交Git的审计源码不冒称已有Git blob。

## 当前实际执行结果

独立新工具c7c12a1云CPU181项测试通过、覆盖率98.68%，当前与旧33cd严格仅一行父spec格式差异；测试回执e0da0d97。对同一原父40f/C4与当前C5实际全hash重审113.5秒，exit0/effective_update_verified=true，独立新报告ac82943e；旧父manifest、runtime99ac、旧33cd/失败8711仍保持原字节。最终当前run联合回执e02da337包含19项真实证据门，旧pending/失败均另列保留。新增审计工具尚未Git提交，不能冒称已发布生产Git blob。
