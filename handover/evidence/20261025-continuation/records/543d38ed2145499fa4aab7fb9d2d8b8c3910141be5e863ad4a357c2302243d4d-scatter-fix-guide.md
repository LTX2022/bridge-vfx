# Scatter / Instancer Troubleshooting Guide

## The Lop/instancer Node

The Instancer LOP scatters prototype assets onto point positions from a SOP
source. It's the USD-native equivalent of Copy to Points in SOP context.

### Key Parameters

| Parameter | Purpose | Common Values |
|-----------|---------|----------------|
| `pointsoppath` | SOP path generating scatter points | `/obj/POINTS_SRC/null1_OUT` |
| `method` | Instancing method | `pointinstancer` (efficient) |
| `transformsourcemode` | How transforms come from points | `extsop` (external SOP) |
| `protopattern` | Which stage prims are prototypes | `/tree_debris* /dry_tree*` |
| `protosourcemode` | Where prototypes come from | `second` (2nd input) |
| `protoindexsrc` | How prototype index is chosen | `pointattr` or `random` |
| `indexattr` | Point attribute for prototype index | `index` |
| `handlemissingprototypes` | What to do with missing protos | `skip`, `warn`, `error` |
| `onlycopyprotoprims` | Copy only prototype prims or full subtree | `0` or `1` |
| `primpath` | Output prim path | `/scattered_assets` |
| `setorient` | Use orient attribute | `1` |
| `setscale` | Use pscale attribute | `1` |
| `hidesourceprims` | Hide original prototype prims | `1` |
| `seed` | Random seed | `42` |

### Inputs
- Input 0: Prototype source stage (usually a null node collecting references)
- Input 1: Same prototype source (when `protosourcemode=second`)

## Common Problems and Fixes

### Problem 1: "Invalid prim: null prim" (40+ warnings)

**Cause**: `protopattern=*` matches ALL prims in the prototype stage, including
null/empty prims inside referenced USD files.

**Fix**:
```python
# Set protopattern to match only real model prims
bridge("set_parm", node_path="/obj/RENDER/INSTANCES",
       parm_name="protopattern", value="/tree_debris* /dry_tree*")
# Skip missing prototypes instead of erroring
bridge("set_parm", node_path="/obj/RENDER/INSTANCES",
       parm_name="handlemissingprototypes", value="skip")
# Copy full prototype subtree (not just top prim)
bridge("set_parm", node_path="/obj/RENDER/INSTANCES",
       parm_name="onlycopyprotoprims", value=0)
```

### Problem 2: Random prototype selection ignores VEX index

**Cause**: `protoindexsrc=random` ignores the `i@index` attribute set in VEX.
Each point gets a random prototype regardless of the VEX logic.

**Fix**:
```python
# Use point attribute for prototype selection
bridge("set_parm", node_path="/obj/RENDER/INSTANCES",
       parm_name="protoindexsrc", value="pointattr")
# Ensure indexattr matches the VEX attribute name
bridge("set_parm", node_path="/obj/RENDER/INSTANCES",
       parm_name="indexattr", value="index")
```

The VEX in the attribwrangle should set:
```vex
i@index = (rand(sid+2) < 0.6) ? 1 : 0;  // 60% index 1, 40% index 0
```

### Problem 3: "Primitive is embedded in a composition arc"

**Cause**: The prototype prim is inside a reference/sublayer composition arc
that can't be directly accessed without flattening.

**Fix**: Set `handlemissingprototypes=skip` to silently skip these. The
accessible prims will still be instanced correctly.

### Problem 4: Wrong camera in render settings

**Cause**: `karmarendersettings` `camera` parm points to a non-existent prim.

**Fix**: Find the actual camera prim path:
```python
# Check what the camera LOP creates
bridge("get_node_parms", path="/obj/RENDER/camera1", max_parms=50)
# Look for 'primpath' parm value, then set it in render settings
bridge("set_parm", node_path="/obj/RENDER/karmarendersettings",
       parm_name="camera", value="/cameras/camera1")
```

### Problem 5: Circular dependency / recursion

**Cause**: Scatter SOP chain placed INSIDE the instancer node, creating a
circular dependency (instancer cooks -> needs points -> cooks internal SOP ->
needs instancer output).

**Fix**: Keep the scatter SOP chain OUTSIDE the instancer, in a separate
`/obj/POINTS_SRC` geo node. Reference it via `pointsoppath`.

## Scatter SOP Chain Setup

Standard non-recursive scatter chain in `/obj/POINTS_SRC`:

```
grid1 -> scatter1 -> attribwrangle1 -> null1_OUT
```

### grid1 (Sop/grid)
Surface to scatter on. Match ground size:
```python
bridge("set_parm", node_path="/obj/POINTS_SRC/grid1", parm_name="sizex", value=20)
bridge("set_parm", node_path="/obj/POINTS_SRC/grid1", parm_name="sizey", value=20)
bridge("set_parm", node_path="/obj/POINTS_SRC/grid1", parm_name="rows", value=50)
bridge("set_parm", node_path="/obj/POINTS_SRC/grid1", parm_name="cols", value=50)
```

### scatter1 (Sop/scatter)
Point generation with Poisson relaxation:
```python
bridge("set_parm", node_path="/obj/POINTS_SRC/scatter1", parm_name="npts", value=22)
bridge("set_parm", node_path="/obj/POINTS_SRC/scatter1", parm_name="relaxiterations", value=40)
bridge("set_parm", node_path="/obj/POINTS_SRC/scatter1", parm_name="relaxpoints", value=1)
bridge("set_parm", node_path="/obj/POINTS_SRC/scatter1", parm_name="forcetotal", value=1)
bridge("set_parm", node_path="/obj/POINTS_SRC/scatter1", parm_name="seed", value=42)
```

### attribwrangle1 (Sop/attribwrangle)
VEX to set per-point attributes:
```vex
int sid = @ptnum * 12345 + chi("seed");
float yrot = rand(sid) * M_PI * 2;
@orient = quaternion(yrot, {0,1,0});
f@pscale = fit01(rand(sid+1), 0.1, 0.3);
i@index = (rand(sid+2) < 0.6) ? 1 : 0;
@N = @N;
```

Set via:
```python
vex = '''int sid = @ptnum * 12345 + chi("seed");
float yrot = rand(sid) * M_PI * 2;
@orient = quaternion(yrot, {0,1,0});
f@pscale = fit01(rand(sid+1), 0.1, 0.3);
i@index = (rand(sid+2) < 0.6) ? 1 : 0;
@N = @N;'''
bridge("set_parm", node_path="/obj/POINTS_SRC/attribwrangle1",
       parm_name="snippet", value=vex)
```

## Verification Checklist

After any scatter fix:
1. Cook the scatter source: `bridge("cook_node", path="/obj/POINTS_SRC/null1_OUT")`
   - Should return `points > 0`, `errors: []`, `warnings: []`
2. Cook the instancer: `bridge("cook_node", path="/obj/RENDER/INSTANCES")`
   - Should return `errors: []`, `warnings: []`
3. Cook the full RENDER chain to catch downstream issues
4. Save the HIP: `bridge("save_hip")`
