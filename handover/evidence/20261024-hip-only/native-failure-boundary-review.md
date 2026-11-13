# 首个失败边界只读核查

核查者：/root/hip_native_failure_readonly。

未发现可静态确定的必然启动缺陷；证据不足以给出Hython内部根因。实际argv为固定H21 hython、冻结graph_job_worker.py、--job、JSON参数，exe/script存在且脚本parents[4]指向冻结根。未输出JSON参数或intent/env/凭据。

最末已证明：supervisor创建child，Houdini创建独立偏好目录21.0/houdini.env。首个未证明：worker最早Python入口。worker_identity.json写入点晚于模块导入、catalog校验、解析、构造、注册图编译、输入核验及scheduler绑定，缺失该文件不能直接归因于许可、CPU、导入或编译。stdout/stderr为空，无error/result/HIP。scope.finish失败关闭不是已证明的首因。

下次最小诊断建议是在最早Python入口、导入完成、解析完成、证据初始化前后落盘固定阶段名和时间，不写job/env/凭据。本次未实施、未运行DCC/采样/import重放、未改代码或扩查旧目录。
