# H21首次保存上下文最小修复合同

## 已复现问题

旧插件原字节的manifest保存单例同样出现PRODUCER_SAVE_UNPROVEN。四个公开参数dcmfilename、productName、checkpoint_basename、checkpoint_basedir保留相同raw/channel，但首次save把software-task.hip改为owned.hip，$HIP/$HIPNAME展开值随之变化。上一轮真实producer的公开settings等节点也记录了untitled上下文依赖；只修改测试准备不能关闭正式链风险。

## 实现边界

1. GraphJobWorker已完成输入、预算、源码及进程证据验证，addon加载后，在首次_host_identity场景读取、_lease和建图之前，准备唯一operation自有HIP路径。
2. 路径严格复用现有result_path.parent/(operation_id+'.hip')与owned_file验证；必须新鲜、位于当前作业根内、不经过符号链接，既有文件拒绝。模型不能提供路径。
3. 只调用本机H21官方hou.hipFile.setName设置内存文件名，并读回path确认；不保存、不加载、不建图、不生成完成回执。后续租约及场景身份从该路径开始，失败沿现有worker失败/停止链处理。
4. 实际scene.save_hip继续执行fresh-path、before/after完整合同一致、HIP内容hash及保存快照验证；不豁免$HIP参数变化，不修改预算、scene epoch规则、签名来源或停止防线。
5. 使用相同自有路径完成随后保存/同进程重开；不从模型或handler返回值另选路径。准备路径不改变既有18个诊断检查点数量。

## 必要软件验证

- 可信worker确在场景身份/租约/首次图操作前准备路径；初始仅改内存name且目标文件不存在。
- 路径逃逸、符号链接、既有文件以及原生setName/path读回不一致均拒绝，不开始图操作。
- 正式生成器的软件API边界完成首次保存；公开$HIP/$HIPNAME参数前后稳定，真实保存/重开/内容与归属断言保留。
- 修正owned-reopen测试准备应在建图/首次lease前设置同样的新鲜路径，不预置工程、receipt或成功事实；旧2.0及新2.1兼容均保留。
- 底层软件hipFile缺setName时只补其官方内存路径语义，不在控制端加入测试专用跳过分支。

## 文件责任与完成定义

C单写graph_job_worker.py、workbuddy_assembly.py的software hipFile局部及必要直接worker测试；A单写owned-reopen测试helper，插件保存比较不改；root负责证据与最终集成。独立审查通过后实施，不启动DCC；本轮验证仍只是软件层，真实HIP和性能尚未证明。
