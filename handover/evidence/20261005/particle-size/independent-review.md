# P02 parameters_only 独立源码复核（2026-10-05）

结论：限定接收两个新增文件作为有界参数计划/读回 helper；本次范围内未发现确定 P1/P2。审查者未参与实现，仅静态读源码、接口、冻结摘要及既有日志；未运行测试、进程或真实软件，未改实现。

- 批准映射符合 `product_control_definitions.py:118`、capture checklist P02：p∈[0,100]，a=1+p/100，min=size/a、range=size*(a-1/a)，100对应[size/2,2size]；0切回const并恢复独立size，不写碰撞半径。size限定[0.0001,100]；非法、非有限及正幅度数值坍缩拒绝。
- 使用两版捕获的point/pscale、set、uniform、minplusrange、custom/id菜单，禁止blend/postprocess/stepping；不推断原生随机样本。P02专用SHA256子seed限定int32非负范围，与粒子顺序无关。
- basis严格绑定task/build/root/node/size/seed/id字段；计划冻结拓扑、输入、simulation几何、basis及相关参数。ID需实际point integer/1 int32非数组值、数量匹配且唯一；点重排需新计划，旧冻结计划拒绝。
- 参数需undriven、unlocked、enabled、visible；菜单token及表示方式固定。计划摘要之外还重建完整允许写集合/guards，拒绝重签后的越界写及marker；post-readback验证实际参数目标与未写冻结事实，并从读回range反推幅度。
- 信任边界仅为认证host collector传入的facts；origin/task_owned/basis自hash不能提供独立认证。Main须采集真实lease/build/ID/basis，在既有fenced事务内先gates后values并复读校验；共享writer、回滚及持久化尚未集成，不据此推断实际宿主可执行性。
- 返回明确为`parameters_only`，保留`actual_random_pscale_by_stable_id`、`copytopoints_pscale_consumption`、`cross_frame_and_reopen_stability`缺口。完整P02继续BLOCKED；还需认证basis/ID collector、出生/跨帧重开稳定性和实例消费事实。无producer/operation完成签发。

核对准确测试名：`tests/unit/test_native_particle_size_program.py`。既有`unit-02.log`覆盖8项：两版端点/参数读回、缺facts、driver/gates/types/menu、身份/拓扑/basis/几何漂移、非法数值/ID、稳定ID/子seed/重排、错误读回/可变计划篡改、0恢复保留其他数据；`Ran 8 tests in 1.153s / OK / EXIT_CODE=0`。这是显式底层参数/node/geometry软件替身日志，不是新HOM、随机几何或正式进程实跑；unit-01不计入最终结论。

独立读字节SHA256与`commands.json`、`modified-files.sha256`一致：

- source：`33ffd567f76bc9bb8773be33fb5a7111179d262b8e1b8cf77a5d4b773a95b617`
- test：`7c109e86c12f7d6243369f95d9c90783762cbc18874777e2ede2f3036336c810`
- unit-02.log：`ae60d365f2768d503289613478ea7442838af56126d9c135965c419eb9717348`
- delta.patch：`edbc47798b0f2fb23b80f09723da1edc77e93e0d012ba2f70284e252a9139110`
- 两版静态capture文件：`b471e37687a73179bcfe3f6a422c526e05a5f2a4b893968f7ed3c188bd8b4052`

可按以上边界接收helper；不得解除`PARTICLE_SIZE_RANDOM_RANGE_AND_BASE_SIZE_CONTRACT_REQUIRED`或标为完整控制PASS。
