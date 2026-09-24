# 夜间候选80题逐条实质复审

原Parquet未修改。此前schema/来源/短读审计不足以判定题目正确；本次逐条推导，keep才建议准入，uncertain与exclude都应移出严谨pilot，不补造样本。科学知识未外部文献核验，只将能直接推导/基础机制无歧义的题列keep。

{
  "math": {
    "train": {
      "keep": 23,
      "exclude": 7,
      "uncertain": 2
    },
    "val": {
      "uncertain": 1,
      "keep": 5,
      "exclude": 2
    }
  },
  "knowledge_mcqa": {
    "train": {
      "uncertain": 18,
      "exclude": 11,
      "keep": 3
    },
    "val": {
      "exclude": 4,
      "uncertain": 3,
      "keep": 1
    }
  }
}

| ID | 原split | 决策 | 理由 |
|---|---|---|---|
| math-316c92ed5e84f625fd3a | train | keep | Δ(u²)=2/∇u/²，因此u常数且u(0)=0，唯一u≡0。 |
| math-07f9881d82ddfd9fba84 | train | exclude | 要求判断并提供证明；GT1不能验收证明。独立公平coin假设亦未明示。 |
| math-9f900599f3b34875e2c4 | train | keep | 标准单位权单边移位：对正交基e_n，Ke_n→0而//Se_n//=1，距离≥1；K=0达1。 |
| math-6fecf116c198b55ce973 | train | keep | 正初值上下界迭代m↦2√m、M↦2√M均趋4，夹逼极限4。 |
| math-680104154f95d33558b9 | train | keep | 枚举1..10三变量全部解乘积144与54，和198；已独立CPU枚举。 |
| math-4b388c6f4e19e09cfe04 | train | keep | Q[π,√11]≅Q(√11)[t]维1，加x,y维3，非零主理想降维至2。 |
| math-271f87f7e221ca99af6a | train | keep | 正x趋0，第一因子渐近x^-1，第二因子渐近x，积趋1；实数分数幂自然定义域右侧。 |
| math-ef416b2b97bb17bf7f96 | train | keep | 设s=a+b,t=c/s且ab≤s²/4，界为4(2/t+10+24t+16t²)，t=1/4最小100。 |
| math-dec38fa6cae4da5e8192 | train | exclude | 没有指定距离范数；且题称Y⊂X错误，积分0连续函数未必f(0)=0；还直接给答案要求验证。 |
| math-c169e701885bf53e0f91 | train | keep | x=cos t,y=sin t,z=cos2t代入线积分；各项周期积分为0。 |
| math-3ab95f01e119c82af379 | train | exclude | 分母省略号未明确币值集合；若标准1,5,10,25,50有5个(x^k-1)因子，整体符号负，与正292矛盾。 |
| math-0df8a5ba33371f8556de | train | keep | π(x)~x/log x，故比值趋0。 |
| math-4a8a82107cc0dce5dad1 | train | keep | x=1时生成函数(1-r)^-1，各系数1。 |
| math-48aa0fe17f9197850b73 | train | keep | x须>0，-3x³+5x²-x≤1（在x=1取等），右侧x+1/x≥2，唯一x=1。 |
| math-43397f49959914c7f214 | train | keep | 项=(1/n²)-(1/(n+1)²)，望远镜和1。 |
| math-63ffb0d7c42bd9ba610b | train | exclude | 源函数在x=0未定义，须先指定可去延拓才能求导；延拓后9!*(-5^6/6!)=-7875000正确，但原题缺定义。 |
| math-3d8d56fc4da28e7c5507 | train | uncertain | 极值三角多项式的集中问题，尚无独立严谨推导，不据GT0批准。 |
| math-db65afe784dd290b4313 | train | keep | Ito漂移为(6+β)W_t dt，β=-6。 |
| math-64146a9d44183905a001 | train | uncertain | Sobolev阶数/符号及矩条件需要严格论证；请求判断证明而非纯数值，暂不准入。 |
| math-a10cb78d27e2c8feb01f | train | keep | 两次分部积分给积分=f(0)+f(π)=2，因此f(0)=1。 |
| math-9c5936d26ea869526160 | train | exclude | 边极小非平面不唯一。15点K5细分可有20边，K3,3细分可有18边；GT40错误。 |
| math-997e8ae35460fbee002d | train | keep | B_t关于0对称，sin奇函数，期望0。 |
| math-ec5d40786cf887cbd6d1 | train | keep | Laurent展开仅z^-2k，无z^-1项，留数0。 |
| math-58fd573620b399a23d54 | train | keep | 对称二阶指标对有10种，交换两对反对称，相当10维空间的反对称矩阵，C(10,2)=45。 |
| math-01c7d47a9d50c236ac62 | train | keep | 整数n时每周期积分缩放，[-π,π]积分恒4。 |
| math-3212dd39f522bd599118 | train | keep | Γ(x)~1/x，Γ(-x)~-1/x，绝对比值趋1。 |
| math-7ad8aee4ec6f7c825f5b | train | keep | x=π/2时g=0，g′=-(1+sin0)=-1，外积分导数因子1，结果-1。 |
| math-59dce45d638be20b2e9c | train | keep | 两积分渐近e^(x²)/(2x)、e^(2x²)/(4x)，比值渐近1/x→0。 |
| math-33b2cf765b7d22069f7c | train | keep | l1对偶范数sup_n/(-1)^n/n/=1，e1取等。 |
| math-256ee733ffeb8eb449e9 | train | exclude | 未限制n，n=1时只有一个极大正规子群，不是3；且题目要求判定证明，数字3不足。 |
| math-cbc66129f4430a9f347c | train | exclude | 要求找任意可行epsilon，0.005等也正确；固定GT0.01造成正确答案误判。 |
| math-87ad5e389bd68354257a | train | keep | 负半轴一根；正半轴e^x/x²在x2最小e²/4≈1.847，整数k≥2出现两根，最小2。 |
| math-1b37c68f8fc0ac2ed15c | val | uncertain | x=-1代入满足，但全部实根唯一性尚未独立证明，不凭答案准入。 |
| math-018ccc89c12a18ab9fa9 | val | keep | 设t=x²+x≥-1/4，约束整数a=0..8；t>1最小比值8，t<1下界-0.45；和36。 |
| math-542d274f696e3784db06 | val | keep | 在F25按α²=α-2递推乘法，首次α^n=1在n24；CPU独立枚举。 |
| math-50a647e8f3d5cd19e02c | val | keep | 模10000用周期500，2^(3^(4^5) mod500) mod10000=352，四位0352；CPU验证。 |
| math-8bdce3355c1808bf29ca | val | keep | 沿y=0有f(x,0)=0，x偏导0。 |
| math-22032b5f0136d14968b4 | val | exclude | 证明题不是数值题，且未限定k≥1，k0时n奇数和=-n而不是0。 |
| math-a472c7bee373ded88a76 | val | keep | 上下端点切触判别式为0，联立得正a14、b9，和23。 |
| math-45756cf9507f4b0229ef | val | exclude | 要求矩阵不是标量；n1时X0和X1均可，标量GT0不能完整验收。 |
| knowledge_mcqa-784c3bf189ddcfb5bafd | train | uncertain | 罕见代谢病未具体说明，理想氨基酸配方不能仅据题干唯一推出植物互补方案。 |
| knowledge_mcqa-f01ac6ab5d86ecbd4fa4 | train | exclude | Ia=Ib意味着A=B，C与F两个选项表达式相同，非单一正确答案。 |
| knowledge_mcqa-5ffaaf46671fc03945a4 | train | exclude | ³H正常β衰变Q约18.6keV，而非题述负eV；核能与电子结合能混淆，前提错误。 |
| knowledge_mcqa-d72c986d54f90b259776 | train | uncertain | B功能域与G糖基化机制均可能，缺指定实验依据不能唯一识别。 |
| knowledge_mcqa-fce3bc68e3502893f004 | train | uncertain | 单体结构不足推出更高内禀保真度；没有突变率或酶学证据。 |
| knowledge_mcqa-4dca9acef75553158519 | train | uncertain | 刚体自旋纹理适用性取决于形变/动力学参数，题干无充分模型，不以对称性标签判定。 |
| knowledge_mcqa-ac3e937be4843ac0efeb | train | exclude | 病例/对照中的暴露比例不是感染/未感染的发病风险，不能直接(28-4)/28算感染者归因风险。 |
| knowledge_mcqa-5d82db355ddcd6d54640 | train | uncertain | Lyα约10^4K温标合理，但fixes温度和最小质量依赖密度/冷却条件，未独立验真。 |
| knowledge_mcqa-8c37316ad581b3c829bb | train | exclude | 阈值387.5nm，实际给定入射300..387.5nm，只有部分UV-B及部分UV-A；GT entire UV-B不严格成立。 |
| knowledge_mcqa-774efce035df290d6598 | train | uncertain | C直接通道抑制与F胞外钙螯合均可降低电流；所给观测不能区分机制。 |
| knowledge_mcqa-f158111880d3f55f5a89 | train | uncertain | 叶酸陷阱是合理机制，但不足独立验证其解释特定高叶酸风险，B也涉及临床机制。 |
| knowledge_mcqa-093115afe4613a96c28f | train | exclude | 末尾同时要求完整bold格式与仅一个选项字符，输出要求冲突；机制亦需验证。 |
| knowledge_mcqa-a8fafd1711be98ca2c4d | train | uncertain | Tm变化不足唯一推出rigidifying机制，B/G/I等因果机制需要结合实验。 |
| knowledge_mcqa-57ed3e9941eee1af2b37 | train | uncertain | 情景提示腺病毒E1A，但选项写EIA且未文献核验；严格保留池暂缓，不标错。 |
| knowledge_mcqa-6248d1723cd6c2828a6b | train | exclude | 40.3%参考误差不能唯一推出负号原因；校准偏置等同样可能，题设缺计算式。 |
| knowledge_mcqa-6ccf16ff814edb7a33a4 | train | uncertain | 临床氮代谢机制涉及多因素，C不是由给定数字直接证明，保留待专业核验。 |
| knowledge_mcqa-0af5b8dc3ef9cf6a237d | train | exclude | γ*归一光子能量=2，不满足一般Thomson低能条件，未给特殊几何；前提不自洽。 |
| knowledge_mcqa-ee074e5327662707a52a | train | exclude | 添加变性蛋白却给c_N而非总浓度，无法由质量守恒得到GT1.5e-5。 |
| knowledge_mcqa-f590810657b1be390bc8 | train | uncertain | 无染色质拓扑数据，不能从缺失区直接唯一归因为TAD，B共享调控也可能。 |
| knowledge_mcqa-5cd00a9a9f7379d434f3 | train | uncertain | 大气吸收需波段/观测史外部依据；本轮不凭记忆认证。 |
| knowledge_mcqa-f1ba4f86455ee4804887 | train | exclude | 明确把electron+antineutrino说成W+产物，电荷守恒矛盾；GT实际反转题干粒子。 |
| knowledge_mcqa-97c9cb8b292463347a7b | train | keep | 分子伴侣屏蔽暴露疏水面防聚集/错折叠，F吻合，其他选项与题干机制不符。 |
| knowledge_mcqa-2229064fe7d2e150135b | train | uncertain | 忽略间隙水又以bound water解释不构成必然矛盾，但ν0.35不足反推单一微观原因。 |
| knowledge_mcqa-6fb69c96542e4cf54829 | train | exclude | 未给协议电路/纠缠资源定义，无法推出triplet x/p相关性；题目依赖缺失理论模型。 |
| knowledge_mcqa-a19373e8213a723ee525 | train | keep | 由题干给定力mg-eE=0直接得E=mg/e，唯一A。 |
| knowledge_mcqa-bf11bbcae8deaec74361 | train | exclude | D总电阻增大、E剩余支路电流不变、H总功率下降都成立，非单选。 |
| knowledge_mcqa-094fef7158b66b0d99d6 | train | uncertain | 压力展宽可能支持总气压，但需谱线过程和非LTE等依据，暂不高置信准入。 |
| knowledge_mcqa-88b0b45af270267a42de | train | keep | e^(-βδ)=1/e直接得δ=1/β，唯一B。 |
| knowledge_mcqa-945ca844d12cd192b932 | train | uncertain | 临床鉴别缺进一步资料，A与E等机制可能并存，不作专业正确性认证。 |
| knowledge_mcqa-392cecb1183f27d00bf8 | train | uncertain | 观测不到水分变化不能唯一反推离子外流；测量效能等解释尚未排除。 |
| knowledge_mcqa-ecd471aa91e7fd488fe6 | train | uncertain | X射线宽带含连续与谱线，C与H相对贡献取决于温度/仪器响应，缺波段。 |
| knowledge_mcqa-7b98fdc7bbdb664ba7cc | train | uncertain | 原子数与高相关不足选出唯一最适方法；强关联下hybrid DFT不保证适用。 |
| knowledge_mcqa-c77da4a3b6f4043b0fa4 | val | exclude | 给每kg氮平衡但无体重与瘦体重蛋白比例，不能推绝对kg。 |
| knowledge_mcqa-b8b76da8b37a01a509af | val | uncertain | WKB误差依赖能量/曲率，A近势垒顶也会显著失效，重叠不是充分最大误差条件。 |
| knowledge_mcqa-350d5d0f1dc1a8394578 | val | uncertain | 可识别apoCIII但抑制类型需实验体系依据，不能只凭特征推非竞争抑制。 |
| knowledge_mcqa-bd78d37850601432ccae | val | exclude | 低pH使S²⁻减少并不能解释铜比锌更低沉淀率；CuS低溶解度与暗示趋势不支持GT机制。 |
| knowledge_mcqa-10491d016a7b36aa0e40 | val | uncertain | Dirac约化方向合理，但h与ħ记号、2系数/核势类型不清，多个说明层次选项重叠。 |
| knowledge_mcqa-c7a95f48c8a11bdcef6b | val | exclude | 一N且质量分数5.89%→14.01/0.0589≈237.86g/mol；无匹配选项，GT205错误。 |
| knowledge_mcqa-bd24122855627b4dc744 | val | keep | ξ=√(E²-Δ²)在正支求导E/√(E²-Δ²)，B；物理DOS取正支。 |
| knowledge_mcqa-65d106392a7c5948a78b | val | exclude | 凝结高度需各物种分压/丰度及饱和压函数参数；题干不足，E比GT C合理。 |
