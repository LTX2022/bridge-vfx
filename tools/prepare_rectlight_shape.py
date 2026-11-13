#!/usr/bin/env python3
"""离线准备已授权RectLight新目标任务；不启动宿主、模型或MCP。"""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1]
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
    sys.path.insert(0,str(ROOT/'packages'/name/'src'))

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-delivery',required=True,type=Path)
    parser.add_argument('--output-root',required=True,type=Path)
    parser.add_argument('--creative-task-id',required=True)
    parser.add_argument('--instruction',required=True)
    parser.add_argument('--plan',required=True,type=Path)
    parser.add_argument('--execution-plugin',required=True,type=Path)
    args=parser.parse_args(argv)
    from houdini_bridge.official_karma_observation import file_record
    from vfx_pipeline.rectlight_shape_preparation import prepare
    result=prepare(args.source_delivery,args.output_root,args.creative_task_id,args.instruction,
        plan_record=file_record(args.plan),execution_plugin=args.execution_plugin)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
