# Simulation Reference (from Houdini official offline manual)

Extracted from $HFS/houdini/help/ ZIPs. Use `query_help` for any doc not listed.

> ⚠️ **本文档是摘录压缩版，含 32 处 `(truncated)` 截断**（单条目超长被切断，关键定义
> 常在后半段）。只当索引用；**查完整定义请直接读官方 zip 原文**：
> ```python
> import zipfile
> z = zipfile.ZipFile(r"C:/Program Files/Side Effects Software/Houdini 21.0.631/houdini/help/pyro.zip")
> text = z.read("flames.txt").decode("utf-8", errors="replace")
> ```
> 本机 zip 路径：`C:/Program Files/Side Effects Software/Houdini 21.0.631/houdini/help/`
> （pyro.zip / anim.zip / basics.zip 等，文件名 = help.search 返回的 file 字段）。

---

## Pyro / Fire / Smoke

### Topic Guides (pyro.zip)

#### pyro/intro

```
= Introduction to Pyro =

[Image:/images/pyro/shockwave.jpg]

Pyro refers to Houdini's volumetric fluid simulation package. The pyro solver
is used for capturing the motion of fire, smoke, and explosions,
but can also be used to simulate other fluid-like phenomena, such as mist or an
avalanche.

NOTE:
    In contrast to [FLIP|/fluid/liquids], pyro does not use particles to track
    the fluid. Since particles are very useful for resolving the surface, pyro
    is not well-suited for simulating liquids.

== Getting started with pyro using shelf tools ==

The tools on the [Simple FX shelf|/shelf/] generate pyro simulation networks using the [Pyro Solver SOP|Node:sop/pyrosolver], which is a SOP level wrapper around the pyro dynamics building blocks. These tools provide a fast and friendly user experience, and avoids the need to build a dynamics network manually.

You can alternatively use the tools on the [Pyro FX shelf|/shelf/] to put down example DOP pyro setups. They create pyro networks that include _sourcing_ on the at the geometry level, a _DOP network_ for the simulation, and an _output object_ to import results of the simulation back into a renderable object. 

TIP:
    The tools on the [Simple FX shelf|/shelf/] are typically a better alternative as they are simpler to get started with, more user friendly, and don't require a separate dynamics network.

All of these are extremely useful for creating instant simulations that can be further modified to integrate with your scene. 

== Related pyro nodes ==

=== Sourcing ===

Sourcing is responsible for the injection of new quantities into the simulation.
For example, you may want to continuously add soot and heat inside a chimney to
animate smoke rising out of it. To do this, you would first generate these
source volumes using SOPs, then merge them into the simulation.

The recommended method to create the source volumes is by rasterizing point attributes. This approach allows for easy inspection and manipulation of sourced quantities. It also naturally accommodates more complex sourcing (such as for shrapnel trails), since you can use the results of a particle simulation to emit smoke and fire.

[Icon:SHELF/convert_to_fire] |
    [Pyro Source|Node:sop/pyrosource] |        
        Converts the source geometry into points with attributes (such as
        `temperature` and `density`). You can manipulate these attributes to
        change the character of the fire/smoke generated from the source. For
     ... (truncated)
```

#### pyro/explode

```
= Creating explosions =

[Image:/images/pyro/explosion.jpg]

== Sourcing ==

The [Pyro Burst Source|Node:sop/pyroburstsource] node creates the sourcing for the core of the explosion and lets you shape how the explosion will look. You can either choose an core point, or if no point is selected, it will create a point as the source. It will then create cone shaped trails from the center of the explosion outwards.

NOTE:
    Pyro source parameters are controlled by attributes, so the input points should not be animated.

:task: Set how large to make the explosion:
    Increase or decrease the __Initial Size__ parameter on the __Burst Shape__ tab.

:task: Change the direction of the explosion:
    Modify the x/y/z __Direction__ parameter on the __Burst Shape__ tab.
    
:task: Add/Remove the amount of trails in the explosion:
    Increase or decrease the __Number of Trailings__ parameter on the __Burst Shape__ tab.

:task: Change the particle scale:
    Increase or decrease the __Trailing Separation__ parameter on the __Burst Shape__ tab.
    
:task: Postpone when a burst will occur:
    Set the __Start Frame__ on the __Burst Animation__ tab. 
    
    It will start at frame 1 by default.

:task: Create multiple bursts:
    Use an [Add SOP|Node:sop/add] to create multiple points and wire them into the [Pyro Burst Source|Node:sop/pyroburstsource].
    
    [Image:/images/pyro/burstsource3.jpg]

:task: Randomize the size and shape of multiple bursts:
    # Change the __Initial Size__ dropdown menu to __Set Varying__ on the __Burst Shape__ tab.
    # Modify the __Variation__ and __Seed__ parameters to further randomize the look of each burst.
    
    [Image:/images/pyro/burstsource2.jpg]
    
:task: Control the size and shape of the bursts:
    Press the [Icon:misc/random] button to the right of the __Initial Size__ parameter on the __Burst Shape__ tab. This will insert an [Attribute Adjust Float|Node:sop/attribadjustfloat] node in your node network which will affect the `pscale` attribute since that's what affects the initial size.
    
    NOTE:
        You could alternatively use an [Attribute Wrangle|Node:sop/attribwrangle] node to manually override the `@pscale` attribute.
        
:task: Control the expansion and duration of the explosion:
    Use the controls on the __Burst Animation__ tab.
    
    The __Expansion Over Duration Ramp__ controls when the explosion moves fast and slow. For example, it can start out slow and then move fast, or vice versa.
  ... (truncated)
```

#### pyro/flames

```
= Flames =

== Flame field ==

The `flame` field is an important part of fire and explosion simulations. It stores the remaining lifetime of reactants (such as fuel) that are transported by the flow. The field is replenished via sourcing, and the pyro solver takes care of reducing its values and generating the desired outputs (based on settings on the solver's __Flames__ tab). Depending on how close reactants are to depletion, they can generate various _outputs_. They can emit soot, increase temperature, and cause expansion. In addition, `flame` can be used as the _emission field_ for visualization and rendering.

As a simple example, you may want reactants that release a lot of heat when they are "young", then start emitting soot as they get used up. You can achieve this by appropriately setting the output parameters on the __Flames__ tab of the [pyro solver|Node:dop/pyrosolver_sparse]. See [Outputs|#outputs] for more information.

== Differences with legacy pyro ==

Prior to Houdini 18, pyro simulations involving combustion used a `fuel` field. In hot areas, the `fuel` would ignite, contributing to the instantaneous `burn` field. This `burn` field would in turn refresh `heat`, which captured the emissive parts of the smoke. Finally, outputs would be generated from the
accumulated `heat` and instantaneous `burn` fields.

The new recommended workflow requires the instantaneous burn to be generated in SOPs and brought in as part of sourcing. A good example of this is the [Sparse Fireball|/shelf/spyro_fireball] shelf tool.

* The `burn` volume is created as the source of the initial detonation.
* This instantaneous `burn` is then merged with the `flame` and `divergence` fields of
the object.

This approach has the advantage of predictability and more control. For instance, if you would like the explosive fuel to rise, you can animate the `burn` source with exactly the desired speed.

For scenarios that require spreading of flames over a fuel source, you can use the [Pyro Source Spread SOP|Node:sop/pyrosourcespread]. This node simulates the spreading behavior throughout its input point cloud and is especially useful for controlling spreading fires.

TIP:
    The [Spreading Fire|/shelf/spyro_firespread] tool on the __Sparse Pyro FX__ shelf can set up a simulation of fire spreading across the surface of an object.

== Lifespan == (lifespan)

Pyro `flame` values are increased through sourcing. The recommended merging operation for sourcing into this field on the... (truncated)
```

#### pyro/shading

```
= Shading and rendering =

Pyro shaders control how smoke, fire and explosions look when rendered. Houdini's pyro shaders provide convenient access to all relevant attributes and give you control over every aspect of the rendering process.

[Image:/images/pyro/explosion_gamma2.2.jpg]

<!---
== Setting up ACES using OpenColorIO ==(aces)

For more accurate color display, use the Academy Color Encoding System (ACES). This is an industry standard color management system. 

# Download OpenColorIO config files from this [webpage|https://opencolorio.org/] or using the direct link to [github|https://github.com/colour-science/OpenColorIO-Configs/tree/feature/aces-1.2-config]. 

    On github, click the green icon labeled as __Code__, then click __Download ZIP__ to download the OpenColorIO config files.
    
# Extract the content of the downloaded zip file to where you want to store the configuration files.

# Set `$OCIO` environment variable to the file path of the OpenColorIO configuration file (such as `config.ocio`). 
    
    This is the configuration file inside one of the `aces` folders with the latest version number. You can do this by opening the `houdini.env` (located in the houdini user folder) with a text editor, and append the following code
    
    `OCIO = PATH_TO_MY_EXTRACTED_FILES/OpenColorIO-Configs.../aces_1.2/config.ocio`

# Start Houdini.

# Open the __Edit__ menu and __Color Settings__.
    
    Make sure __OCIO Config__ is using the provided path on the __Color Correction__ tab.

:col:
    [Image:/images/pyro/explosion_gamma2.2.jpg]
    
    """Viewport with gamma 2.2 (default)"""

:col:
    [Image:/images/pyro/explosion_aces.jpg]
    
    """Viewport with ACES enables using OCIO"""

For more information, see [OCIO|/io/ocio] and [Linear lighting and color|/render/linear].

--->

== Understanding Pyro Bake Volume ==

The [Pyro Bake Volume|Node:sop/pyrobakevolume] node provides controls to enhance the look of a pyro solve in the viewport. It also handles automatic material assignment to best match the rendering results to the viewport display, and is designed to provide a similar interface to the [Pyro Shader|Node:vop/pyroadvancedshader]. When scattering is turned on, it bakes out a `scatter` volume that is used by the [Pyro Shader|Node:vop/pyroadvancedshader] to approximate the look of light scattering inside the explosions.

:include /nodes/sop/pyrobakevolume#bakeshader:

:include /nodes/sop/pyrobakevolume#scatter:

== Understanding the Pyro S... (truncated)
```

#### pyro/lookdev

```
= Pyro workflow =

== Overview ==

The speed and emergent shape of a pyro simulation are controlled by a combination of many parameters. This page contains tips and tricks for effectively working with pyro tools and achieving different simulation looks.

Before you begin, the following help pages provide an in-depth explanation of pyro:

- [Introduction to Pyro|intro] - Describes the various components of a simulation, and covers the relevant operators.

- [Understanding how pyro works|background] - A high-level explanation of how pyro simulations are carried out.

- [Sparse vs dense simulations|sparsity] - Important information regarding sparse pyro simulations.

- [Flames|flames] - Explains the `flame` field.

== Visualization ==

Throughout the prototyping process, it is useful to examine the state of the simulation fields. The [Smoke object|Node:dop/smokeobject_sparse] has a vast array of visualization options for these fields. The help for the [Scalar Field Visualization|Node:dop/scalarfieldvisualization] and
[Vector Field Visualization|Node:dop/vectorfieldvisualization] nodes provide more details about the various available options.

The most useful visualization mode is __Multi Field__, since it displays all of the volumes that would be seen when rendering. The help for [Multi-Field Visualization|Node:dop/multifieldvisualization] contains through information about the parameters. The most important settings for affecting the
look are outlined below.

__Density Field__:
    Used for smoke thickness. This should be set to `density`. To make the smoke appear thicker, increase the __Density Scale__.
    
__Diffuse Field__:
    Used to tint the smoke. For example, the [Sparse Fireball|/shelf/spyro_fireball] shelf tool sets the __Diffuse Field__ to `density` and the __Diffuse Ramp__ to a constant color. As a result, the visualized smoke appears dark grey.

__Emission Field__:
    Used to emit light. This should be set to `flame` to ensure that the fiery parts of your simulation glow. __Emission Scale__ controls the amount of emission. To get a sharper border for flames, enable __Emit Range__ and set it to something narrow, such as `0.1-0.2`.

__Emission Color Field__:
    Controls the color of the emitted light. This parameter should be set to `temperature`. In __Physical Blackbody__ mode, the temperature values will get mapped to an emission color and intensity using the blackbody radiation model.

== General workflow ==

Many parameters on the pyro solv... (truncated)
```

#### pyro/sparks

```
= Sparks =

[Image:/images/pyro/sparkler.jpg]

:include /nodes/sop/particletrail#overview:

:include /nodes/sop/particletrail#customize:

For more detailed parameter information, see the [Particle Trail SOP|Node:sop/particletrail] help page.

== Changing the look of sparks ==(look)

There are many controls on the [Particle Trail SOP|Node:sop/particletrail] that allow you to change the look of sparks. In some of the following images, the width has been increased to better illustrate the effect.

=== Detail ===

If you increase the __Substeps__ parameter, it will increase the number of divisions in each line. This will give more detail to the sparks, such as a slight curved shape as they fall toward the ground, and V shapes as they hit the ground and bounce off.
    
[Image:/images/pyro/sparks/substeps.jpg]
    
=== Color ===
    
You can change the color of your sparks using the controls in the __Color__ section on the __Look__ tab. The __Color Along Length Ramp__ parameter is useful for creating a natural looking gradient in your sparks from head to tail. However, you can only have as many colors as there are numbers of __Substeps__.
    
Alternatively, you can choose __Color Over Normalized Age__ if you want to color the sparks from when it was create to when it dies.
    
:col:
    [Image:/images/pyro/sparks/color.jpg]
    
    __Color Along Length Ramp__
:col:
    [Image:/images/pyro/sparks/color2.jpg]
    
    __Color Over Normalized Age__
        
You can turn both of these checkboxes on to use both effects. This will give you individual sparks that are brighter at the tip and darker at the tail, as well as sparks that are brighter when they're born and fade over time.
    
[Image:/images/pyro/sparks/color3.jpg]
    
=== Transparency ===

You can change the opacity of your sparks using the controls in the __Alpha__ section on the __Look__ tab. Similar to color, the __Scale Along Length__ parameter will fade the spark along the length of each individual spark from head to tail, and the __Scale Over Normalized Age__ parameter will fade the sparks from when they were created to when they die.

:col:
    [Image:/images/pyro/sparks/alpha1.jpg]
    
    __Scale Along Length__
:col:
    [Image:/images/pyro/sparks/alpha2.jpg]
    
    __Scale Over Normalized Age__
    
NOTE:   
    Similar to color, these can also be used together to create both effects.
    
=== Brightness ===

To make sparks brighter, you can increase the __Scale__ in the __Intensity__ sect... (truncated)
```

#### pyro/clustering

```
= Clustering smoke and pyro simulations =

"""Creates a clustered (partitioned) pyro simulation with multiple containers, using the selected point geometry as sources. This is useful for large or sparse sources, and for distributing simulations to a farm."""


== Overview ==

_Clustering_ partitions a large or sparsely-distributed smoke or pyro
simulation into multiple (possibly overlapping) fluid boxes instead of one
giant box.

[Image:/images/dynamics/clustering1.png]

Using multiple small boxes has several advantages:

* Can be distributed to multiple processes and/or machines on a farm.

* Solves faster since the computer doesn't have to deal with the empty spaces
between the important parts of the overall simulation.

* The small boxes can be much higher resolution, or multiple resolutions,
whereas a giant box usually must have a lower resolution because of memory
limitations.

The multiple containers created by these tools are _separate simulation
objects_ with _no interaction between each other_. For example, density cannot
move out of one container into an adjacent one. This is usually not a problem
for smoke and fire simulations.


== Creating a clustered smoke/pyro simulation from point sources ==

# Select the object you want to emit from.

# On the __Pyro FX__ shelf tab, click [Icon:SHELF/smokecluster] Smoke Cluster
or [Icon:SHELF/pyrocluster] Pyro Cluster.

    * The tool creates a new network named `<<objectname>>_sourcpts`.

    * The new network contains a [Icon:SOP/scatter][Scatter|Node:sop/scatter]
    node that creates points on the input geometry's surface.

    * These points are then partitioned by a [Icon:SOP/clusterpoints]
    [Cluster Points|Node:sop/clusterpoints] surface node. The clustering
    branches off into nodes operating on the "instance points" (the points that
    will emit smoke/fire) and "cluster points" (the points on which the
    containers will be centered).
    
    * On the "instance point" branch it creates a [Icon:SHELF/convert_to_fire]
    [Pyro Source|Node:sop/pyrosource] and [Icon:SOP/attribnoise]
    [Attribute Noise|Node:sop/attribnoise] nodes to set appropriate values for
    the necessary point attributes, which are then rasterized into volumes.
    
        [Image:/images/dynamics/clustering_sops.jpg]

    * In the DOP network, the tool creates a regular [pyro setup|pyro]. On the
    [Smoke object|Node:dop/smokeobject], it turns on
    __Create Objects From Points__ (in the __Instancing__ tab) and impo... (truncated)
```

#### pyro/pyroinstancing

```
= Basic pyro instancing =

The new pyro instancing system in Houdini lets you instance different pyro sources, change and randomize their attributes, apply transformations, and customize ignition times.

In a nutshell, multiple pyro sources are packed through [Pyro Source Pack|Node:sop/pyrosourcepack] nodes and merged into a library. The individual elements of this library are then scattered through a point source, for example a [Scatter|Node:sop/scatter] node or along curve points. With an [Attribute from Pieces|Node:sop/attribfrompieces] you randomly assign different library elements to the scatter points.

TIP:
    For explanations around pyro source instancing, please see the [Pyro instancing definitions|definitions].

The [Pyro Source Pack SOP|Node:sop/pyrosourcepack] creates a packed source set from its input volumes. A packed source set, however, consists of a packed primitive containing the source volumes, along with the rules on how to apply them to a pyro simulation. In the example below you create a packed source set that includes `density` and `temperature` volumes, with rules that indicate to

* add the source `density` volume to the `density` pyro field,
* pull the `temperature` pyro field towards the target `temperature` volume.

== Packed source sets library ==

NOTE:
    Please note that the following guide is a conceptual example. When working with a real scenario, you should also specify the Pyro Source Pack node's __Frame Range__ parameter.

# On _obj_ level, create a [Geometry|Node:obj/geo] node and dive into it.
# Press ((Tab)) in the network editor and invoke the _Pyro Configure Billowy Smoke_ tool. This will create a small chain of nodes to simulate smoke.
# Locate the `volumerasterizeattributes` node. Source volumes are the output of this node, consisting of `density`, `temperature`, and `v` VDBs.
# Put down a Pyro Source Pack node and connect its input to the output of `volumerasterizeattributes`. The new node will create the packed source set.
# Set the __Name__ parameter on this new node to `torus_smoke`. The output of this node is a packed source set called `torus_smoke`.

NOTE:
    When you look at the Pyro Source Pack sources, you can see the rules for the `density`, `temperature`, and `v` fields - plus a default `burn` field. The `burn` rule is unnecessary here and should be deleted in real scenarios, but it will work for our simplified example.

In the next step you create two more sources from the chain's first five nodes.... (truncated)
```

#### pyro/sparsity

```
= Sparse vs dense simulations =

== Simulation area ==

At any given point during the simulation, the pyro fields are defined inside of the current _container_. The pyro container starts out very small, and the solver constantly expands/shrinks it as the simulation proceeds. To perform its internal resizing, the solver tracks the specified __Reference Fields__, which
can be set on the __Advanced > Resizing__ tab. With the default settings of `density flame`, for instance, the solver will ensure that the simulated region contains all space that has some smoke or flame. See the [Understanding Resizing|#resizing] section below for a concrete example of how resizing is performed.

NOTE:
    You can see the extent of the simulation container by turning on the __Bounding Box__ on one of the enabled visualization options for the [smoke object|Node:dop/smokeobject_sparse]. These controls are located on the node's __Guides__ tab.

The [Pyro solver|Node:dop/pyrosolver_sparse] can operate in either _sparse_ or _dense_ mode.

* In _dense_ mode, the entire container is simulated. This is useful if your gas occupies the whole simulation container or if the velocity values are needed beyond the areas where visible smoke exists.

* In _sparse_ mode, simulation is only performed in the _active_ subset of the container. This mode is generally much more efficient, since it only performs expensive computations in the areas of interest. However, there are some limitations. See the [Sparse Solving|#sparsity] section for more information.

NOTE:
    Prior to Houdini 18, pyro simulations could only be performed in dense mode.

== Sparse solving == (sparsity)

The pyro solver will operate in sparse mode if both the solver and the object have __Enable Sparse Solving__ turned on. These parameters can be found on the __Properties__ tab of the object and the __Advanced > Sparsity__ tab of the solver. Since these two parameters are enabled by default, simulations will be done sparsely, unless explicitly put into dense mode.

The only other condition is that all resizing of simulation fields must be performed in [full tiles|#fulltiles] (this concept will be explained below). As of Houdini 18, external resizing should only be done while sourcing, by the [Volume Source DOP|Node:dop/volumesource]. Therefore, if __Enlarge Fields to Contain Sources__ is enabled on this node, __Enlarge by Full Tiles__ must be as well.

NOTE:
    2D simulations and OpenCL are not supported in sparse mode.

Err... (truncated)
```

#### pyro/advanced

```
= Advanced pyro instancing =

NOTE:
    This workflow guide uses special terms like _spawn points_ or _packed sets_. If you're not familiar with this terminology, please go to the [Pyro instancing definitions|Link:definitions] page for more information. 

With the help of the new [Pyro Spawn Sources|Node:sop/pyrospawnsources] and [Pyro Source Instance|Node:sop/pyrosourceinstance] nodes you can achieve full control over the pyro instances and their attributes.

The [Pyro Spawn Sources|Node:sop/pyrospawnsources] node creates spawn points. You can connect a point source, e.g. a scatter or a curve, or let the node create a single point at the origin (which can be moved and rotated freely using the [Transform SOP|Node:sop/xform]). Spawn points identify which packed set will be used and store basic animation parameters like __Start Frame__ and __Source Speed__. At each frame, a spawn point may generate a single instance point. The spawn points can be set to loop, in which case they will birth new instance points at different times during the simulation.

The node's parameter values are stored on point attributes of spawn points. These properties on attributes can be modified to control the instances, e.g. through a downstream [Attribute Adjust Float|Node:sop/attribadjustfloat] node.  You can see the available attribute names (`name`, `startframe`, etc.) when you hover the mouse over a parameter to get its tooltip. Aside from the parameters, there are also `P`, `pivot`, and `orient` attributes that control placement of the instance. You can merge spawn points from multiple [Pyro Spawn Sources SOPs|Node:sop/pyrospawnsources] if you want to modify them together or before conversion to instance points.

The spawn points are then fed to a [Pyro Source Instance|Node:sop/pyrosourceinstance] operator. When a spawn point activates, this node creates an instance point. The instance points, on the other hand, are fed to the [Pyro Solver|Node:sop/pyrosolver]. The [Pyro Source Instance|Node:sop/pyrosourceinstance] node can register rule overrides for the point attributes. It is, for example, possible to scale `temperature` within a random minimum-maximum range and create hotter and cooler sources.

Below you find a step-by-step guide for the creation of an advanced pyro instancing setup. As in the [basic pyro instancing|Link:pyroinstancing] workflow, everything starts with a source library.

== Creating the library ==

The library contains all sources. A source can be a prec... (truncated)
```

### Pyro Configure Presets

#### pyro_configure_fire

```
= Pyro Configure Fire =

== Overview ==

There are several Pyro Configure examples available through the [tab menu|/basics/tabmenu]. These are similar to [shelf tools|/shelf/index] that put down networks of nodes for learning purposes. The __Pyro Configure Fire__ example illustrates a fast moving fire.  It shows a minimal fire setup that can be used as a template for building fire in your scene.

:video:
    #src: /videos/pyro/coppyro/Fire.mp4

== Important nodes ==

`SOURCE`:
    Wire a Mono layer into this node to adjust where the smoke emits from. This node controls the thickness of the fire emission. A value of `0` will have no fire and `1` will have the full thickness.

`pyro_configure1`:
   Adjusts the resolution of the fire.  This is the number of voxels across the default imaging window.  Higher resolutions will take considerably more time and memory.

`layertovdbleafpoints2`, `pyro_sourcefromlayer2`, `pyro_sourcefromlayer3`:
    The VDB has to be activated so you can source into it.  [Layer to VDB Leaf Points|Node:cop/layertovdbleafpoints] handles the activation from the `SOURCE` layer, while the [Pyro Source from Layer|Node:cop/pyro_sourcefromlayer] handles the actual sourcing.  The thickness and inputs for these two nodes should match.

`pyro_block_begin2`:
    The start of the simulation loop.  All nodes inside the convex hull (highlighted area) will run every simulation step. The simulation is clipped from `-1` to `1` by default, and can be controlled by modifying the __Clip X/Y/Z__ parameters.

`pyro_dissipate2`:
    Controls how fast the temperature decays.  Temperature is used for the glow of the fire, so a slower decay will result in longer flames.

`pyro_lightambient2`:
    Computes lighting for the fire's smoke using an ambient light source. Increasing smoke density (with the __Density Scale__ parameter) increases the contrast of self-shadows.

`rasterizevolume2`:
    Renders the fire into a layer.  The `camera_ref` can use an imported camera from the [Camera Import COP|Node:cop/cameraimport] to change the view or resolution of the render.  The __Emission__ parameters can be used to make the fire brighter or control the envelope of the glow.

== Learning from this example ==

:task: Create different fire sources:
    Change the input to `SOURCE`. You can use any shape, or even a [Font COP|Node:cop/font] to make the smoke sourced from text.

:task: Slow down how fast the fire moves:
    Reduce the __Scale__ on the `pyro_buoyancy1` node to... (truncated)
```

#### pyro_configure_fireball

```
= Pyro Configure Fireball =

== Overview ==

There are several Pyro Configure examples available through the [tab menu|/basics/tabmenu]. These are similar to [shelf tools|/shelf/index] that put down networks of nodes for learning purposes. The __Pyro
Configure Fireball__ example illustrates a rising fireball and demonstrates how divergence can be used to drive a Pyro simulation.

:video:
    #src: /videos/pyro/coppyro/FireBall.mp4

== Important nodes ==

`SOURCE`:
    Wire a Mono layer into this node to adjust where the smoke emits from. This node controls the thickness of the fire emission. A value of `0` will have no fire and `1` will have the full thickness. Note that the input is animated to create a pulse of explosion for a few frames.

`pyro_configure1`:
    Adjusts the resolution of the fireball.  This is the number of voxels across the default imaging window.  Higher resolutions will take considerably more time and memory.

`layertovdbleafpoints3`, `pyro_sourcefromlayer5`, `pyro_sourcefromlayer4`:
    The VDB has to be activated so you can source into it.  [Layer to VDB Leaf Points|Node:cop/layertovdbleafpoints] handles the activation from the `SOURCE` layer, while the [Pyro Source from Layer|Node:cop/pyro_sourcefromlayer] handles the actual sourcing.  The thickness and inputs for these two nodes should match.

`pyro_block_begin3`:
    The start of the simulation loop.  All nodes inside the convex hull (highlighted area) will run every simulation step. The simulation is clipped from `-1` to `1` by default, and can be controlled by modifying the __Clip X/Y/Z__ parameters.

`rescale_divergence`:
    The hot areas of the simulation are set to expand.  This node remaps the temperature field into how much divergence to apply. It ensures no expansion occurs below a minimal temperature of `0.1` and that a temperature of `1` would trigger `8` units of divergence.  Too little divergence and there is no apparent effect, too much and the simulation rapidly explodes.

`pyro_lightscatter1`:
    Computes internal scattering of light within the fireball's smoke. This takes the glow of temperature and diffuses it by bouncing it internally through the density field.  This is most effective at creating an internal glow look to dark smoke.

`pyro_lightambient3`:
    Computes lighting for the fire's smoke using an ambient light source. Increasing smoke density (with the __Density Scale__ parameter) increases the contrast of self-shadows.

`rasterizevolume3`:
    Rende... (truncated)
```

#### pyro_configure_flame

```
= Pyro Configure Flame =

== Overview ==

There are several Pyro Configure examples available through the [tab menu|/basics/tabmenu]. These are similar to [shelf tools|/shelf/index] that put down networks of nodes for learning purposes. The __Pyro
Configure Flame__ example illustrates a slow moving flame. It shows a simple flame setup that can be used as a template for building flames in your scene.

:video:
    #src: /videos/pyro/coppyro/Flame.mp4

== Important nodes ==

`SOURCE`:
    Wire a Mono layer into this node to adjust where the smoke emits from. This node controls the thickness of the fire emission. A value of `0` will have no fire and `1` will have the full thickness. Note that the input is animated to create a pulse of explosion for a few frames.

`streakblur1`:
    Since the source is added once per frame, if the flame moves too far between adding the source it will generate distinct bars.  By blurring the source in the direction the flame will rise, a smooth flame can be generated.

`pyro_configure1`:
    Adjust the resolution of the flame. This is the number of voxels across the default imaging window.  Higher resolutions will take considerably more time and memory.

`layertovdbleafpoints1`, `pyro_sourcefromlayer1`, `pyro_sourcefromlayer2`, `pyro_sourcefromlayer3`:
    The VDB has to be activated so you can source into it.  [Layer to VDB Leaf Points|Node:cop/layertovdbleafpoints] handles the activation from the `SOURCE` layer, while the [Pyro Source from Layer|Node:cop/pyro_sourcefromlayer] handles the actual sourcing. The thickness and inputs for these two nodes should match.

`pyro_block_begin1`:
    The start of the simulation loop.  All nodes inside the convex hull (highlighted area) will run every simulation step. The simulation is clipped from `-1` to `1` by default, and can be controlled by modifying the __Clip X/Y/Z__ parameters.

`pyro_dissipate2`:
    Controls how fast the temperature decays. Temperature is used for the glow of the flame, so a slower decay will give longer flames.

`pyro_viscosity1`:
    To smooth out the velocity of the flame and create a viscous effect, this node applies a blur to the velocity VDB.  Note that the __Pixels__ measurement will measure voxels for VDBs.

`pyro_lightambient1`:
    Computes lighting for the fire's smoke using an ambient light source. Increasing smoke density (with the __Density Scale__ parameter) increases the contrast of self-shadows.

`sub2`, `sub1`:
    The just-sourced flame is part... (truncated)
```

#### pyro_configure_billowysmoke

```
= Pyro Configure Billowy Smoke =

== Overview ==

There are several Pyro Configure examples available through the [tab menu|/basics/tabmenu]. These are similar to [shelf tools|/shelf/index] that put down networks of nodes for learning purposes. The __Pyro Configure Billowy Smoke__ example illustrates a simple rising dense smoke cloud. It can be used as a template for building smoke in your scene.

:video:
    #src: /videos/pyro/coppyro/Billowy_Smoke.mp4

== Important nodes ==

`SOURCE`:
    Wire a Mono layer into this node to adjust where the smoke emits from. This node controls the thickness of the smoke emission. A value of `0` will have no smoke and `1` will have the full thickness.

`pyro_configure1`:
    Adjusts the resolution of the smoke.  This is the number of voxels across the default imaging window.  Higher resolutions will take considerably more time and memory.

`layertovdbleafpoints`, `pyro_sourcefromlayer1`:
    The VDB has to be activated so you can source into it.  [Layer to VDB Leaf Points|Node:cop/layertovdbleafpoints] handles the activation from the `SOURCE` layer, while the [Pyro Source from Layer|Node:cop/pyro_sourcefromlayer] handles the actual sourcing.  The thickness and inputs for these two nodes should match.

`pyro_block_begin1`:
    The start of the simulation loop.  All nodes inside the convex hull (highlighted area) will run every simulation step. The simulation is clipped from `-1` to `1` by default, and can be controlled by modifying the __Clip X/Y/Z__ parameters.

`pyro_lightambient1`:
    Computes lighting for the smoke using an ambient light source. Increasing smoke density (with the __Density Scale__ parameter) increases the contrast of self-shadows.

`rasterizevolume1`:
    Renders the smoke into a layer.  The `camera_ref` can use an imported camera from the [Camera Import COP|Node:cop/cameraimport] to change the view or resolution of the render.

== Learning from this example ==

:task: Create different smoke sources:
    Change the input to `SOURCE`. You can use any shape, or even a [Font COP|Node:cop/font] to make the smoke sourced from text.

:task: Control the amount of smoke emitted:
    Change or animate the __Brightness__ parameter on the `bright2` node to control how much smoke is created.

:task: Control the amount of smoke dissipation:
    Adjust the parameters on `pyro_dissipate1` to control how fast the smoke dissipates into the background.

:task: Control the pump direction for the emitted smoke:
    Adjus... (truncated)
```

#### pyro_configure_colorsmoke

```
= Pyro Configure Color Smoke =

== Overview ==

There are several Pyro Configure examples available through the [tab menu|/basics/tabmenu]. These are similar to [shelf tools|/shelf/index] that put down networks of nodes for learning purposes. The __Pyro
Configure Colored Smoke__ example illustrates 3 colored smokes interacting. It also demonstrates how to use the feedback wires to add additional fields to the simulation.

:video:
    #src: /videos/pyro/coppyro/ColorSmoke.mp4

== Important nodes ==

`SOURCE`:
    Wire a Mono layer into this to adjust where the smoke emits from.  A value of `0` will have no fire and `1` will have the full thickness.

`COLOR`:
    Wire an RGB layer into this to set the color of newly emitted smoke.

`pyro_configure1`:
    Adjust the resolution of the smoke.  This is the number of voxels across the default imaging window.  Higher resolutions will take considerably more time and memory.

`layertovdbleafpoints6`, `pyro_sourcefromlayer10`:
    The VDB has to be activated so you can source into it.  [Layer to VDB Leaf Points|Node:cop/layertovdbleafpoints] handles the activation from the `SOURCE` layer, while the [Pyro Source from Layer|Node:cop/pyro_sourcefromlayer] handles the actual sourcing.  The thickness and inputs for these two nodes should match.

`pyro_block_begin6`:
    The start of the simulation loop.  All nodes inside the convex hull (highlighted area) will run every simulation step. The simulation is clipped from `-1` to `1` by default, and can be controlled by modifying the __Clip X/Y/Z__ parameters.

    The `feedback` input port is only read on the first frame of the simulation.  After that, the `feedback` output port will contain what was passed into the `feedback` input port of `pyro_block_end6` on the previous frame.  Note that the [cable structure|/copernicus/cables] must be the same. The types and names of the wires must not change.

    All feedback wires that match the __VDBs to Activate__ pattern will be activated for new sources, and all feedback wires that match the __VDBs to Advect__ will be advected by velocity.  These both are the default `*`, so the VDBs passed through named `Cd` and `Cd_weight` will be resized and advected.  Note this pattern is also used to decide if the default `density` and `temperature` VDBs will be updated.

`extra_Cd_fields`, `cableunpack3`, `cablepack2`:
    To properly simulate color, two VDBs are needed. One is a vector VDB of the pre-multiplied color, the other is a scalar ... (truncated)
```

#### pyro_configure_dryice

```
= Pyro Configure Dry Ice =

== Overview ==

There are several Pyro Configure examples available through the [tab menu|/basics/tabmenu]. These are similar to [shelf tools|/shelf/index] that put down networks of nodes for learning purposes. The __Pyro
Configure Dry Ice__ example illustrates a falling dry ice effect. It demonstrates setting up colliders in Pyro, and shows how to send more than one thing into the `passthrough` port by using [cables|/copernicus/cables].  It also shows how to limit the rasterizing of smoke to a depth map.

:video:
    #src: /videos/pyro/coppyro/DryIce.mp4

== Important nodes ==

`SOURCE`:
    Wire a Mono layer into this node to adjust where the smoke emits from. This node controls the thickness of the fire emission. A value of `0` will have no fire and `1` will have the full thickness. Note that the input is animated to create a pulse of explosion for a few frames.

`COLLIDER`:
    This forms the collision object.  It is a [SOP Geometry COP|Node:cop/sopimport] that imports the pig head into COPs.  To use different geometry, the `file1` node should be changed to point to the correct texture maps to texture the new geometry properly.

`sopinvoke1`:
    Converts the collision geometry into an SDF VDB for colliding.

`cablepack1`, `cableunpack1`:
    Both the source layer and collision VDB need to be added to the simulation through the `passthrough` port.  Since there is one port, the two things are packed into a single [cable|/copernicus/cables] with `cablepack1` and unpacked with `cableunpack1`.

`pyro_configure1`:
    Adjust the resolution of the dry ice.  This is the number of voxels across the default imaging window.  Higher resolutions will take considerably more time and memory.

`layertovdbleafpoints5`, `pyro_sourcefromlayer9`:
    The VDB has to be activated you can source into it.  [Layer to VDB Leaf Points|Node:cop/layertovdbleafpoints] handles the activation from the `SOURCE` layer, while the [Pyro Source from Layer|Node:cop/pyro_sourcefromlayer] handles the actual sourcing.  The thickness and inputs for the two should match.

`pyro_block_begin5`:
    The start of the simulation loop.  All nodes inside the convex hull (highlighted area) will run every simulation step. The simulation is clipped from `-1` to `1` by default, and can be controlled by modifying the __Clip X/Y/Z__ parameters.

`rasterizegeo1`:
    The collision geometry is rasterized to provide a backplate to render the dry ice over.  The depth of the geometry... (truncated)
```

### Pyro Configure Presets

### Key Pyro SOP Nodes

#### sop/pyrosolver

```
﻿#type:     node
#context:  sop
#internal: pyrosolver
#icon:     DOP/pyrosolver
#since: 18.0

= Pyro Solver =

"""Runs a dynamic Pyro simulation."""

== Overview ==

The Pyro Solver is a wrapper around a DOP network to simplify the running of Pyro solves.

NOTE:
    The interface has been redesigned in Houdini 19.0.

@inputs

Volumes for Sourcing:
    #id: input0
    Provides the sources for the Pyro simulation. This should be a set of named volumes. The exact names required are determined by the __Sourcing__ tab.   The [Pyro Source SOP|Node:sop/pyrosource] and [Volume Rasterize Attributes SOP|Node:sop/volumerasterizeattributes] are useful tools for creating source volumes.

Volumes or Geometry for Collision:
    #id: input1
    The second input provides the collisions for the Pyro simulation. It should be a SDF VDB, such as the second output of the [Collision Source SOP|Node:sop/collisionsource] or the main output of the [VDB From Polygons SOP|Node:sop/vdbfrompolygons].  If the collision is animating, points with a `v` attribute can be used to describe the motion.  The two outputs of the [Collision Source SOP|Node:sop/collisionsource] can be merged and used as the second input to provide this.

@parameters

Reset Simulation:
    #id: resimulate
    
    Clears the entire simulation cache.   Ctrl-click to also jump to the
    start frame.
    
Start Frame:
    #id: startframe
    
    What frame on the Houdini playbar that the simulation should begin at.
    
Quick Setups:
    #id: quicksetups
    This menu lets you run some simple scripted setups to help with the most common tasks.
        
    Initialize Sources:
        Populates the __Sourcing__ tab based on the incoming volumes.

    Initialize Smoke:
        Initializes the solver to simulate smoke.

    Initialize Fire:
        Initializes the solver to simulate fire.

    Initialize Explosion:
        Initializes the solver to simulate an explosion.

    Add Color Source:
        Creates an additional source
... (truncated, full doc is 50960 chars)
```

#### sop/pyrosource

```
#type: node
#context: sop
#icon: SHELF/convert_to_fire
#internal: pyrosource
#since: 17.0

= Pyro Source =

""" Creates points for sourcing pyro and smoke simulations. """

The Pyro Source SOP converts its input geometry into points suitable for
sourcing pyro and smoke simulations. This SOP adds specified attributes to the
generated points, which can be rasterized and imported into desired DOP fields
by the [Volume Source|Node:dop/volumesource] node. Pyro Source also contains a
handful of initialization presets for driving common simulation scenarios.

@inputs

Geometry to Source From:
    Input geometry. When __Mode__ is set to __Surface Scatter__ or __Volume
    Scatter__, the geometry must correspond to a surface; in the latter case,
    the surface must also have a resolvable interior.

Rest Geometry:
    If provided, this geometry will be used to generate points. These points
    are then moved to conform with the current configuration of the deforming
    geometry.

@outputs

Particles:
    Generated points, with the assigned attributes.

@parameters

Group:
    #id: group
    When specified, only the subset of the input geometry corresponding to this
    group is used.

Group Type:
    #id: grouptype
    What the __Group__ is made of.

Initialize:
    #id: initialize
    Configures the node according to the selected preset. __Source Burn__ and
    __Source Fuel__ can be used to drive legacy and sparse pyro simulations,
    respectively, whereas __Source Smoke__ is meant for smoke simulations.
    __Source Color__ creates color (`Cd`) and color density (`Alpha`) attributes
    that can be imported by the [Volume Source|Node:dop/volumesource] node using
    the __Blend__ operation.

Mode:
    #id: mode
    Controls which points are exported by the node.

    Surface Scatter:
        Points are scattered on the surface of the input geometry.
    Keep Input:
        Points of the incoming geometry are used unchanged.
    Volume Scatter:
        Points are scatter
... (truncated, full doc is 5206 chars)
```

#### sop/pyrobakevolume

```
#type:     node
#context:  sop
#internal: pyrobakevolume
#icon:     SOP/pyrobakevolume
#since: 18.5

= Pyro Bake Volume =

"""Helps develop the volume look both for viewport display and rendering after the pyro solve."""

== Overview ==

Pyro Bake Volume provides controls to enhance the look of a pyro solve in the viewport. It also handles automatic material assignment to best match the rendering results to the viewport display, and is designed to provide a similar interface to the [Pyro Shader|Node:vop/pyroadvancedshader]. When scattering is turned on, it bakes out a `scatter` volume that is used by the [Pyro Shader|Node:vop/pyroadvancedshader] to approximate the look of light scattering inside the explosions.

NOTE:
    [Pyro Post-Process|Node:sop/pyropostprocess] serves a similar purpose and is designed to work with [Pyro Shader - Classic|Node:vop/pyroshader]. You can use those operators if you don't need the extra emissive elements of the [Pyro Shader|Node:vop/pyroadvancedshader].

== Using Pyro Bake Volume with the Pyro Shader ==(bakeshader)

The [Pyro Bake Volume|Node:sop/pyrobakevolume] node contains a [Pyro Shader|Node:vop/pyroadvancedshader], which is automatically assigned to the processed volumes. The embedded shader references parameters on Pyro Bake Volume to ensure that the render matches the viewport. Therefore, you can create copies of the Pyro Bake Volume node and render different variants without adjusting material assignments at the object level. 

TIP:
    You can dive inside the Pyro Bake Volume node to access the Pyro Shader and its controls.

Although most of the Pyro Shader's features are available on the Pyro Bake Volume node, there are a few extra parameters on the shader that are not available in the viewport. To see the effect of these parameters, you need to render the volumes. 

The following are additional things you can control with the [Pyro Shader|Node:vop/pyroadvancedshader].

* Clamp or remap the smoke density, or scale it by anot
... (truncated, full doc is 27898 chars)
```

#### sop/pyroburstsource

```
﻿#type:     node
#context:  sop
#internal: pyroburstsource
#icon:     SOP/pyroburstsource
#since: 18.5

= Pyro Burst Source =

"""Creates points suitable for sourcing into pyro simulations to create explosions, muzzle flashes, shockwaves, and detonation rings."""

:video:
    #src: /videos/firecrackers.mp4


== Overview == 

This node takes the incoming static points and replicates clusters of points around them in some arbitrary "blob" shapes that capture an explosion's initial form when __Burst Type__ is set to __Explosion__ or __Muzzle Flash__.

[Image:/images/sop/pyro_point_to_burst.svg]

Points are scattered onto the surface of a "blob" shape when the burst shape is generated. 

[Image:/images/sop/pyro_burst_trailingpoints.svg]

When __Burst Type__ is set to __Shockwave__, the points are generated onto a three dimensional sphere, and can be limited to a specific slice on this sphere, giving you a flat shockwave ring spreading on ground or a three dimensional dome blast shape. 

When __Burst Type__ is set to __Blast Rings__, the points are generated onto multiple flat two dimensional rings that are aligned inside a three dimensional dome. This can be used to create rings spreading above the fireball as the dome blast shape expands. This type of behavior can be observed mostly on very large scale, such as nuclear explosions.

These leading points are then trailed towards the center of the explosion to give a desirably dense point distribution inside the burst shape. Finally, each point is animated outwards from the center of the burst to give a sense of expansion.

NOTE:
    It is important that the number of incoming points stay constant over time.

WARNING:
    When working on explosions from a fast moving object, it is possible to animate the position (`P`) of the incoming points, however other attributes controlling burst properties should never be animated over time. 

== Burst components ==(components)

    A burst is made of replicated clusters of points o
... (truncated, full doc is 47901 chars)
```

#### sop/pyropostprocess

```
#type:     node
#context:  sop
#internal: pyropostprocess::2.0
#version:  2.0
#icon:     SOP/pyropostprocess
#since:    19.0

= Pyro Post-Process =

"""Applies common post-processing effects to the results of Pyro solves."""

The Pyro Post-Process node provides common post-processing operations for Pyro
solvers. It can also bake flame values into the density map to ensure Mantra
picks up purely emissive regions.

@parameters

== Post Process == 

Compute Min/Max Values:
    #id: computeminmax

    Computes the minimum and maximum values of each volume and stores
    it as a primitive attribute of the same name.  If the volume is
    vector type and is converted to VDB, the maximum length is stored.

Convert to VDB:
    #id: conv_vdb

    Convert these volumes into VDBs.  Zero areas will be discarded
    as inactive.  Volume sets, such as `vel.x`, `vel.y`, and `vel.z`,
    will be merged into a single vector VDB.

Combine Volumes:
    #id: conv_combine

    When enabled, VDBs with the same name are combined into a single primitive.
    This feature is only available if volumes are converted to VDBs.
    
    In areas where different volumes of the same name intersect, the maximum
    value is used for the combined result.

Use 16bit Float:
    #id: conv_usefp16

    Marks the volume to use 16-bit float values.  This requires half
    the memory of full 32-bit values, but can be slower to process.
    Houdini volumes will be 16-bit in memory and on disk.  VDBs are
    only 16-bit when saved to disk.

    NOTE: For Houdini volumes this will only convert volumes to 16-bit, not
    convert back to 32-bit.  Use the [Volume Compress|Node:sop/volumecompress]
    to switch volumes back to 32-bit.

Cull Volume:
    #id: conv_cullvolumenames

    When enabled, the active region of the specified VDB will be restricted to
    the active region of the __Cull Mask Volume__. This can help reduce the
    memory footprint of the primitives while retaining the volume values in
    nee
... (truncated, full doc is 4055 chars)
```

#### sop/pyrospawnsources

```
#type:      node
#context:   sop
#icon:      SOP/pyrospawnsources
#internal:  pyrospawnsources
#since:     19.5

= Pyro Spawn Sources =

""" Creates spawn points for sourcing pyro simulations with packed sets. """

The Pyro Spawn Sources SOP creates spawn points for sourcing pyro simulations using packed source sets. These points identify the relevant packed sets and store some basic animation data, such as when the source is to engage, how quickly it should play back, and how frequently it should repeat. Additionally, this operator facilitates some basic source rule overrides to adjust rules that come with the packed set.

The spawn points can be modified downstream to adjust (or randomize) their properties, which are stored on point attributes; for example, you can use [Attribute Adjust Float|Node:sop/attribadjustfloat] to randomize the `startframe` values, causing the different sources to engage on different frames. Key point attributes of spawn points are listed below.

`name`:
    Name of the packed source set that we want to instance.
`P`:
    Location of the instance in world space.
`orient`:
    Orientation of the instance in world space.
`pivot`:
    The local pivot point for this instance.
`startframe`:
    The instance is activated on this playbar frame.
`endframe`:
    If greater than `startframe`, the instance will not be active beyond this
    playbar frame.
`looplength`:
    If this value is no smaller than `1`, then the source sequence will loop.
    The looping sequence starts at `startframe` and is `looplength` frames in
    length.
`startoffset`:
    When the instance first engages (on `startframe`), it starts sourcing at
    this offset within the packed source set's frame range.
`offsetlength`:
    Length of the subsequence to use from the packed set's full frame range.
    For example, if `startoffset` is `0` and `offsetlength` is `5`, then only
    offsets `0-5` will be used for sourcing. If `offsetlength` is smaller than
    `0`, then all fra
... (truncated, full doc is 5447 chars)
```


---

## Fluid / Liquid

### Topic Guides (fluid.zip)

#### fluid/index

```
= Fluids =
#bestbet: fluid
#billboard: /images/billboards/ocean_and_sky.jpg
#headerheight: 20vh

"""How to set up fluid and ocean simulations."""

@subtopics

== For beginners ==
:: [dopversussop]

~~~ SOP WORKFLOW ~~~

== Particle Fluids (SOP) ==
:: [sopboundaries]
:: [sopminimalsetup]
:: [sopsourcing]
:: [sopcollisions]
:: [sopmovingdomains]
:: [sopoceanwaves]
:: [Whitewater|sopwhitewater]
:: [sopupressing]
:: [sopnarrowband]
:: [sopdensmult]
:: [sopfilling]

== Viscous fluids (SOP) ==
:: [sopvischoney]
:: [sopviscvarhoney]

== Optimization (SOP) ==
:: [sopcaching]

== FLIP Configure tools (SOP) ==
:: [sopconfigflip]
:: [sopconfiglava]
:: [sopconfigtank]
:: [sopconfigbeach]
:: [sopconfigocean]
:: [sopconfigwave]

~~~ DOP WORKFLOW ~~~

== Particle Fluids (DOP) ==
:: [liquids]
:: [directingparticlefluid]
:: [surfacing]
:: [splashingwater]
:: [bubbles]
:: [narrowband]
:: [tips]

== Viscous Fluids (DOP) ==
:: [flipviscosity]
:: [lava]

== Oceans (DOP) ==
:: [oceans]
:: [Whitewater|whitewater]

== Optimization ==
:: [compress]
:: [Distributing fluid simulations|/dyno/distribute]


```

#### fluid/liquids

```
= Particle fluids =

== Overview ==

Houdini has several different methods for simulating liquids such as water, mud, lava, and so on, each with different strengths and weaknesses.

To simulate fluids such as smoke and flame, use [pyro simulation|/pyro/pyro].

See [how to set up the viewport and desktop|/dyno/setup]. We highly recommend you use the technical [desktop|/basics/panes] (__Windows > Desktop > Technical__) so you have quick access to the tree view and details view.

Particle fluid simulations use particles to represent the fluid. For visualization and rendering, the particles are _surfaced_ -- that is, a surface is created based on the particles.

:vimeo:FLIP fluids
    #id: 116176349
    #keywords: FLIP solver, flip tank shelf preset, flip tank tool, fluid tank, RBD object, feedback scale, density, velocity 

== FLIP (particle + grid) fluids ==

FLIP fluid solvers copy the particle's velocities onto a grid, uses a _project non-divergent_ step to calculate a new velocity field, then copies the new field back onto the particles. 

Pros |
    Avoids explosions and stray particle spray.

    The lower number of required sub-steps can make FLIP very fast.
    
    Allows new particles to be added to the system.
    
    Allows editing particles using POPs and SOPs.

    Unbounded, can flow freely throughout the scene. FLIP uses a container to calculate the velocities, but it is recreated at every frame. The container is mostly useful as a limit outside which stray particles will be deleted.

Cons |
    
    Uses a limit box. The limit box can be quite large however. It prevents a stray high-speed particle from forcing the solver to grow its fields so large that you run out of memory.
    
Velocities |
    Stored on the particles.

Manipulate |
    Forces. Full control using POPs and SOP point editing.

Distribution |
    Arbitrary slices. Works best with fast-flowing liquid.

Usual sub-stepping |
    1x. However, if a fast-moving liquid or a fast-moving obstacle need to collide accurately, you will still need to sub-step.

== Creating particle fluids == (emission)

* The __Particle Fluids__ shelf tab has several tools for creating particle fluids:

    * [Icon:SHELF/convert_to_fluid] [FLIP Fluid From Object|/shelf/flipfluidfromobject] creates a blob of fluid in the shape of the selected geometry.
    
    * [Icon:SHELF/flip_tank] [FLIP Tank|/shelf/fliptank] creates a rectangular body of particle fluid inside an invisible box.
    
    * [Icon:SHELF/... (truncated)
```

#### fluid/lava

```
= Viscous fluid tools =

"""Viscous fluids are FLIP simulations that use a temperature attribute to drive viscosity."""

== Overview ==

The tools on Viscous Fluids shelf set up FLIP simulations, which react to temperature changes. The viscous fluid tools set up a temperature attribute that drives the viscosity. For example, as the temperature of lava cools, so does the viscosity.

:vimeo: Melting object
    #id: 142306097

== Melt Object vs Lava From Object ==

The [Melt Object|/shelf/meltobject] and [Lava From Object|/shelf/lavafromobject] tools are very similar, as they both turn geometry objects into a particle fluids with a temperature attribute that affects viscosity. The main difference is that the [Melt Object|/shelf/meltobject] tool doesn't apply any shader. The [Lava From Object|/shelf/lavafromobject] assigns a shader to get a basic glowing lava look.

You would typically want to use [Melt Object|/shelf/meltobject] whenever you have an object that will change state over time. For example, a warm chocolate bunny that would slump over and then cool off and become solid. Whereas the [Lava From Object|/shelf/lavafromobject] is typically used for simulating lava, since it has the lava shader applied.

Both of these tools are affected by the __Temperature__ parameter on the __Physical__ tab of the [FLIP Object|Node:dop/flipobject]. This parameter sets the initial temperature of the object. The default value is 0.5, which will cause it to melt immediately since the object starts off quite warm. A higher value will give you very hot, free-flowing liquid which cools over time and a lower value would give you cool, highly viscous fluid that heats up and melts.

== Heat Within Object vs Cool Within Object ==(heatvscool)

    The [Heat Within Object|/shelf/heatwithinobject] and [Cool Within Object|/shelf/coolwithinobject] tools are very similar. The main difference is that the heating tool has a high __Increase Rate__ meaning that melting objects will heat up, and the cooling tool has a high __Decrease Rate__ meaning that objects will cool off quickly.
    
    The __Increase/Decrease Rate__ parameters can be found on the [POP Attribute from Volume|Node:dop/popattribfromvolume] node, and work similar to the way the __Temperature Diffusion__ parameters on the [Gas Temperature Update|Node:dop/gastemperatureupdate] node work. They control how quickly the temperature from your heated or cooled object will affect your viscous fluid. 


== Viscous Fluid Tools ==

... (truncated)
```

#### fluid/splashingwater

```
= How to |> make splashing water =

There are two types of liquid simulations you can use to make water: [Icon:DOP/flipobject][Particle Based Fluid|Node:dop/flipobject] or [Icon:DOP/fluidobject][Volume Based Fluid|Node:dop/fluidobject]. 

To make splashing water, you should use particle based fluid (FLIP fluid). [FLIP fluid|Node:dop/flipobject] uses a field of particles to produce splash-like liquid that can move anywhere in a scene. On the other hand, [volume based fluid|Node:dop/fluidobject] uses a sign distance volume which creates a glue-like liquid that is confined to a container.

:vimeo:FLIP fluids
    #id: 116176349

== Make splashing water in a river ==

# Model a river bed for the water to flow, and turn it into a [Icon:DOP/terrainobject][Terrain Object|Node:dop/terrainobject].

    Make sure your terrain is slightly sloped to allow the particles to flow in one direction.
    
# Create a [Icon:SOP/grid][grid|Node:sop/grid] that intersects the riverbed and is slightly below the riverbank. The area between this and the riverbank will be converted into particle fluid.

    [Image:/images/howto/splash_riverbed.jpg]

# Model objects (such as rocks) that protrude from the river bed, and turn them into static objects.

# Modeling the grid with high and low points will not create waves, as the particle fluid is affected by gravity and will sink down when the simulation is run. To create waves use the [Icon:SOP/waveform][Waveform|Node:sop/waveform] tool on the __Deform__ shelf tab to create waves.

# Use the [Icon:SHELF/sculptedparticlefluid][Sculpted Particle Fluid|/shelf/sculptedparticlefluid] tool on the __Particle Fluids__ shelf tab to convert the area between your grid and riverbank to particle fluid.
    
    :fig:[Image:/images/howto/splash_particles.jpg]
        This step is complex, since you will have to first select the fluid surface object, then the terrain object, and finally any obstacles embedded in the river. If there is more than one obstacle you can hold ((Shift)) to select multiple objects. For more information, see the [Sculpted Particle Fluid|/shelf/sculptedparticlefluid] help.

# Use the [Icon:SHELF/whitewater][Whitewater|/shelf/whitewater] tool on the __Particle Fluids__ shelf tab to make even more splashes, as particles are emitted when the sharpness of the wave crest reaches a certain threshold.

The [Icon:SHELF/sculptedparticlefluid][Sculpted Particle Fluid|/shelf/sculptedparticlefluid] tool calculates the volume of the space bet... (truncated)
```

#### fluid/whitewater

```
= Whitewater (DOP) =

The [Whitewater|/shelf/whitewater] shelf tool on the __Particle Fluids__ tab
creates spray, foam, and churn based on an underlying FLIP fluid simulation. It
sets up the [source|Node:sop/whitewatersource] and
[solver|Node:dop/whitewatersolver] for a whitewater simulation. Whitewater
is created from a source [FLIP|/shelf/flipfluidfromobject] simulation based on
several criteria including fluid acceleration, curvature, and vorticity.
Whitewater enhances the look of fluid animation with secondary effects such as
spray, foam, and bubbles.


:video:
    #src: /videos/beach_small.mp4

== Forces == (forces)

Dynamics of the whitewater particles are governed by several mechanisms.

* Acceleration due to __Gravity__ is applied uniformly to all particles.
* With default settings, __Buoyancy__ pushes particles in the opposite direction
  of __Gravity__ and is responsible for surfacing of bubbles.
* The particles move with the underlying liquid's flow as they are passively
  advected through its velocity field.
* Special repellant points on the surface push away nearby whitewater particles,
  breaking up the foam structure and giving rise to a cellular pattern.
* The liquid's surface tension and adhesion result in foam "sticking" to the
  surface, not allowing it to submerge or peel away. These effects can be
  simulated by enabling depth control.
* Density control is responsible for maintaining local whitewater distribution,
  preventing particles from clustering too closely. Additionally, this
  mechanism gives rise to whitewater cohesion, as it fights dispersion.

The [Whitewater Solver|Node:dop/whitewatersolver] allows for fine control of these forces at different depths. For instance, it may be desirable to strictly control density at the surface, but less so for airborne whitewater that should easily separate; this effect can be achieved by attenuating the strength of density control.

== Whitewater Lifecycle == (lifecycle)

The solver takes care of birthing new whitewater particles, using the emission
volume created by the [Whitewater Source|Node:sop/whitewatersource] node to
determine the amount. When __Limit Emission__ is enabled, the present
distribution of whitewater particles is also considered, avoiding over-emission.

Aging and killing of particles is likewise handled by the solver. As simulation
progresses, whitewater ages in an ordinary manner; however, particles do not
have a prescribed lifetime. Instead, a death chance is dynamic... (truncated)
```

#### fluid/surfacing

```
= Particle fluid surfacing and rendering =

To allow you to render the particle fluid, Houdini must "surface" the fluid. That is, build a polygonal surface based on the positions of the particles in the fluid.

<!--
    {Pic}
-->


When you use the shelf tools to set up a particle fluid network, the tools automatically set up a new Geometry object containing the result surface from the fluid simulation (by default called `particle_fluid` or `sculpted_particle_fluid` depending on the tool).

The `particle_fluid` object contains a node importing the particle fluid visualization, and nodes to import and convert the particles into a surface. The [DOP Import node|Node:sop/dopimport] with the visualization has the _display flag_ (blue circle), so it is used for the viewport. The [Particle Fluid Surface node|Node:sop/particlefluidsurface] that creates the surface has the _render flag_ (purple circle) so it is used when you render. You can click the display flag on the Particle Fluid Surface to view the surface in the viewport instead of the particles.

<!--
    {Pic}
-->


TIP:
    If the surface is too rough, you can try connecting a [Peak surface node|Node:sop/peak] to the Particle Fluid Surface output to shrink the surface inward, and then add a [Smooth node|Node:sop/smooth].

TIP:
    You can clip the fluid surface using any container and collision geometry, to prevent interpenetration. Import the container geometry into the fluid surfacing object, use an [IsoOffset node|Node:sop/isooffset] to convert it to an SDF (set __Output type__ to "SDF Volume" and use the __Uniform sampling__ parameter to control the resolution). Then, connect the IsoOffset to the _second_ input of the Particle Fluid Surface node. On the Particle Fluid Surface node, click the __Collision Volumes__ tab and turn on __Subtract Collision Volumes__. You can use this to subtract any geometry from the surface, for example to add air bubbles.
    
```

#### fluid/sopminimalsetup

```
= Minimal fluid setups =

To create SOP fluid simulations, you need a small set of nodes. There are three fundamental methods.

== Waterline ==

This basic network consists of a [FLIP Container SOP|Node:sop/flipcontainer] and a [FLIP Solver SOP|Node:sop/flipsolver] node. With this setup you don't need any external sources.

# On _obj_ level, press ((Tab)) to invoke the TAB menu. Create a [Geometry SOP|Node:obj/geo] node and dive into it.
# Inside the Geometry node, create a FLIP Container node. You can use different container shapes by connecting geometry to the container's input. In the image below you can see a petal-shaped domain, a tube, and the cross-section of Houdini's [Rubber Toy|Node:/sop/testgeometry_rubbertoy].
# Add a FLIP Solver node and connect the first three inputs with the outputs of the FLIP Container.
# In the solver's __Waterline__ tab, turn on __Waterline__.

A particle narrow band layer appears and you can control its __Additional Velocity__ to create the impression of a moving water surface.

[Image:/images/fluid/sopflip_domainshapes.jpg]

* Set __Additional Velocity__ to any value, e.g. `4` for the X parameters to create a water motion. New particles are constantly sourced and deleted to keep the water level constant.

=== Adding collisions ===

To get interaction with objects, splashes and waves there is the [FLIP Collide SOP|Node:sop/flipcollide] node. FLIP Collide works with native or imported objects, as well as VDB and Houdini volumes. Objects and volumes can be animated or deforming. The collision object itself shouldn't be too small, because you might lose important details.

# Add a FLIP Collide node.
# Wire it between FLIP Container and the FLIP Solver node's first three inputs.
# Create or import an object.
# Translate, rotate and scale the object, for example with a [Transform SOP|Node:sop/xform] node.
# Connect the Transform node's output with the fourth input of the FLIP Collide node.

[Image:/images/fluid/sopflip_collision.jpg]

An object, connected to a FLIP Collide node, is internally converted to a volume. To see the collision geometry, turn on the node's blue __Display/Render__ flag. You can change the quality of the collision geometry only through the FLIP Container node's __Particle Separation__ parameter. The smaller the value, the better the collision geometry, but you will also create more voxels and particles. This, on the other hand, increases simulation times and RAM consumption, but also improves the fluid... (truncated)
```

#### fluid/sopconfigflip

```
= FLIP Configure FLIP! =

Houdini's SOP FLIP fluids provide several ready-to-use tools to illustrate some of most common workflows. To access the tools, create a [Geometry SOP|Node:obj/geo] and double-click it to dive into the node. There, press the ((Tab)) key to invoke the TAB menu. Enter `flip configure` and choose [Smallicon:SOP/testgeometry_rubbertoy.svg] `FLIP Configure FLIP!` from the list. Houdini creates a complete network and you can immediately start the simulation by clicking the [Smallicon:PLAYBAR/play_forward.svg] icon in the playbar.

[Image:/images/fluid/sopconfigflip.jpg]

The `FLIP Configure FLIP!` tool shows how to 

* work with varying viscosity,
* transfer UV texture information to a `Cd` color point attribute,
* use the `Cd` attribute to dye the fluid particles.

The tool creates a gradually melting [Rubber Toy SOP|Node:sop/testgeometry_rubbertoy] test geometry with variable viscosity. The toy's texture information is transferred to the particles and the particle fluid surface.

== Main nodes ==

table width="100%">>
    th width="25%">>Node name
    th width="75%">>Function

    tr>>
        td>>`testgeometry_rubbertoy`
        td>> [Test Geometry: Rubber Toy SOP|Node:sop/testgeometry_rubbertoy]. This node is a ready-to-use object that comes with texture map, material definition, and proper UVs.
    tr>>
        td>>
            `fliptank1`
        td>>
            [FLIP Container SOP|Node:sop/flipcontainer]. To use point variable viscosity, the  node's __Varying Viscosity__ parameter is turned on. The custom `Cd` __Point Attribute Name__ is required to transfer colors from the rubber toy's map to the fluid particles. The `Cd` attribute is also used in the `particlefluidsurface1` node's __Transfer Attributes__ parameter.
    tr>>
        td>>
            `setcolor`
        td>>
            [Attribute from Map SOP|Node:sop/attribfrommap]. This node loads the __Texture Map__ and converts the map's colors into a `Cd` point attribute.
    tr>>
        td>>
            `setviscosity`
        td>>
            [Attribute Wrangle SOP|Node:sop/attribwrangle]. The simulation's viscosity values are defined through a short VEXpression. The expression says that all particles with a Y position greater than `0.3` units have a viscosity of `100000`. If a particle's position falls below this threshold, viscosity is set to `100`.
    tr>>
        td>>
            `flipsolver1`
        td>>
            [FLIP Solver SOP|Node:sop/flipsolver]. This node i... (truncated)
```

#### fluid/sopconfigocean

```
= FLIP Configure Ocean Layer =

Houdini's SOP FLIP fluids provide several ready-to-use tools to illustrate some of most common workflows. To access the tools, create a [Geometry SOP|Node:obj/geo] and double-click it to dive into the node. There, press the ((Tab)) key to invoke the TAB menu. Enter `flip configure` and choose [Smallicon:SHELF/guided_ocean_layer.svg] `FLIP Configure Ocean Layer` from the list. Houdini creates a complete network and you can immediately start the simulation by clicking the [Smallicon:PLAYBAR/play_forward.svg] icon in the playbar.

[Image:/images/fluid/sopconfigocean_1.jpg]

The `FLIP Configure Ocean Layer` tool shows how to 

* create a guided ocean layer,
* work with the [FLIP Solver SOP|Node:sop/flipsolver] node's fourth input,
* customize and modify the simulation domain,
* drive fluid particles through an ocean spectrum.

This tool creates a guided FLIP simulation of a particle layer from an ocean surface. The particles are initialized with ocean velocities. The FLIP simulation uses a guiding volume approach to maintain ocean velocities through the simulation. The network modifies the domain volume to make it a collision object for the particles. The depth of the layer will determine how closely the simulation matches the ocean surface. The depth will also determine how well the simulation can capture motion below the surface such as wakes and vortices.

== Main nodes ==

table width="100%">>
    th width="25%">>Node name
    th width="75%">>Function

    tr>>
        td>>
            `tube1`
        td>>
            [Tube SOP|Node:sop/tube]. This node determines the shape of the simulation domain. The object is converted into a VDB volume through the `vdbfrompolygons` node ([VDB from Polygons SOP|Node:sop/vdbfrompolygons]).
    tr>>
        td>>
            `make_mask`
        td>>
            [Subnetwork SOP|Node:sop/subnet]. This node provides a custom __Band__ parameter to adjust a mask. The mask is used to control the depth of the particle layer. __Band__ defines the width of an area in which the mask fades out. Double-click the node to dive into the node. There you can see the network that creates the mask's transition and the __Band__ parameter. Below you can see the mask.

            [Image:/images/fluid/sopconfigocean_2.jpg]
    tr>>
        td>>
            `adjust_domain`
        td>>
            [Subnetwork SOP|Node:sop/subnet]. The domain's volume is modified through this subnetwork to make it acts as a collis... (truncated)
```

#### fluid/sopconfigtank

```
= FLIP Configure Tank =

Houdini's SOP FLIP fluids provide several ready-to-use tools to illustrate some of most common workflows. To access the tools, create a [Geometry SOP|Node:obj/geo] node and double-click it to dive into the operator. There, press the ((Tab)) key and enter `flip configure`. From the list choose [Smallicon:SHELF/flip_tank.svg] `FLIP Configure Tank`. Houdini creates a complete network and you can immediately start the simulation by clicking the [Smallicon:PLAYBAR/play_forward.svg] icon in the playbar.

[Image:/images/fluid/sopconfigtank.jpg]

The `FLIP Configure Tank` tool shows how to 

* create a basic FLIP fluid simulation domain with a waterline,
* turn the particles into a polygon mesh.

The tool adds a container with default dimensions and a narrow band waterline. This setup represents a basic setup and can be used as a starting point for more complex networks.

== Main nodes ==

table width="100%">>
    th width="25%">>Node name
    th width="75%">>Function

    tr>>
        td>>
            `fliptank1`
        td>>
            [FLIP Container SOP|Node:sop/flipcontainer]. This nodes creates a domain where fluid simulation happens. At the domain's boundaries, particles are sourced and deleted to maintain an equilibrium. You can also connect an object to the node's input. This object will then serve as a custom-shaped domain. The FLIP Container is also the place where you turn on physical properties like __Surface Tension__ or __Viscosity__. You can also define custom attributes such as `temperature` or `density`. If you want to increase the number of particles, decrease __Particle Separation__.
    tr>>
        td>>
            `flipsolver1`
        td>>
            [FLIP Solver SOP|Node:sop/flipsolver]. This node is the center piece of the network and brings everything together to simulate the fluid's behavior. The __Waterline__ tab is of particular interest: when the __Waterline__ is turned on, the solver creates an even particle surface. In simulations, where the particles interact with the domain's limits, __Boundary Conditions__ are relevant.
    tr>>
        td>>
            `particlefluidsurface1`
        td>>
            [Particle Fluid Surface SOP|Node:sop/particlefluidsurface]. Turn on the node's __Display/Render__ flag to invoke the creation of a polygon mesh, representing the fluid.

== Tips ==

:task: Change the container size:
    Adjust the `fliptank1` node's __Size__ parameters or connect a custom object to the no... (truncated)
```

#### fluid/tips

```
= Particle fluid tips =

* If a collision/container wall is too thin, the particles can collide with the wall but the pressure solve step may not see it, causing particles to "stack up" against the wall instead of bouncing off it, making the liquid appear to compress and disappear. Increasing the thickness of the collision geometry will fix this (note that you can use different geometry for creating the collision field and for rendering, so you can still render a thin container wall).

    (Alternatively you could decrease the particle scale to the point where the pressure step will work because the collision grid will be fine enough to resolve the thin container wall.)

* If you are animating source/collision geometry at the SOP level, you need to tell the FLIP Solver to look for point-based collision velocities. On the FLIP Solver's __Collisions__ tab, set __Velocity Type__ to "Point". It's usually a good idea to add a [Trail SOP|Node:sop/trail] to your collision object set to "Compute Point Velocities". Once you do that you should see good collision velocities in the visualization.

    (When animating geometry for use with dynamics, remember to use `$T` (floating point time) in animation expressions instead of `$F` (frame number) for proper sub-frame interpolation.)

* To get foam/white-water on splashes, take the velocity field from the fluid simulation and use it to advect "white" particles created within a tolerance of an SDF of the fluid surface.

* If you're seeing unexpected collision behavior, turn on the __Collision Velocity__ visualization option on the FLIP object and make sure the solver is seeing reasonable velocities.

* To create a more interesting fluid from an emitter, use an interesting shape (for example, a torus or tube rather than a sphere) and add noise to the emission velocities.

    The fluid particles use the value of the `v` (velocity) attribute on the point they are birthed from as their initial velocity, so you can control the emission velocities by setting `v` in the geometry network of the source object.

* By default, the fluid particles will be emitted from the _points_ of the geometry. To emit a solid stream of particles, scatter points within a volume and use the scattered points as the emission geometry. However, "shell" emitters with more points at the boundaries and fewer in the interior give more interesting results.

    You can turn off __Stream emission__ on the Particle Fluid Emitter object to emit particles us... (truncated)
```

### Key Fluid SOP Nodes

#### sop/particlefluidsurface

```
= Particle Fluid Surface =

#type: node
#context: sop
#internal: particlefluidsurface
#icon: SOP/particlefluidsurface
#tags: fluid, surface
#version: 2.0
#since: 14.5

"""Generates a surface around the particles from a particle fluid simulation."""

Connect point geometry from a [particle fluid simulation|/fluid/] or a [Vellum fluid simulation|/vellum/] to this node's first input. The node will generate a surface from the outermost points.

(You can surface any points, not just points from a particle fluid sim, as long as the points have a `pscale` attribute. This attribute specifies the virtual radius of each particle in Houdini units.)


== Deleting surface area from inside other volumes/objects == (subtract)

You can optionally subtract geometry from the generated surface before it is converted to polygons. For example, you can prevent the node from generating polygons outside the fluid's container object, or within objects the fluid is colliding with.

# Connect the volumes/geometry you want to subtract from the surface to this node's _second_ input ("Collision objects and volumes").

# In the parameter editor, click the __Regions__ tab and turn on __Subtract collision volumes__.


== Masking filters == (mask)

You can apply filters such as _smoothing_ to the surface using the controls on the [Filtering tab|#filtering].

To mask the effect of a filter with a fog volume:

# Connect the mask volume to this node's _third_ input ("Mask volumes").

# On the __Filtering__ tab, turn on the filter using the checkbox to the left.

# Turn on the __Mask__ checkbox to the right of the filter.

# In the mask controls below the filters, turn on __Mask input__.

    :box:
        #id: mask_input_field
        
        The field next to __Mask input__ lets you specify a group within the input. If you leave it blank, this node will use all geometry in the input. Or you can specify a specific volume by name using group syntax, for example `@name=mask`.


== Previewing part of the
... (truncated, full doc is 21449 chars)
```

#### sop/fluidcompress

```
#type: node
#context: sop
#icon: SOP/fluidcompress
#internal: fluidcompress
#since: 14.5


= Fluid Compress =

"""Compresses the output of fluid simulations to decrease size on disk"""

The Fluid Compress SOP compresses fluid simulations, usually before saving the data to disk.  The compression is generally lossy, in that FLIP particles will be culled below the specified depth, and volume bandwidth is limited by zeroing out values. However, SOPs such as [Whitewater Source SOP|Node:sop/whitewatersource] and [Particle Fluid Surface SOP|Node:sop/particlefluidsurface] are designed to detect compressed fluid input and regenerate any required missing data.

The typical input of this SOP are:

* Particles from a FLIP simulation
* A `surface` field representing the SDF field of a liquid simulation
* Three fields name `vel.x`, `vel.y`, and `vel.z` representing the velocity vector field of a fluid simulation.

The primary methods of compression by this operator are:

* Particle culling below specified depth.
* Partitioning the particles spatially and converting them into packed primitives.
* Volume bandwidth limiting and conversion to sparse VDB format.
* Flagging the VDB's to save as 16-bit on disk, further reducing disk space.

NOTE:
    This SOP creates several detail attributes indicating that the fluid has been compressed. Several of these are also stored to the info block when written to file, making them accessible through the [File SOP|Node:sop/file]'s __Info Load__ mode or the `gstat` command line tool.  These attributes include:

    * `fluidcompress_particleband` and `fluidcompress_volumeband` - the Particle and Volume bandwidth respectively.
    * `fluidcompress_particlesuncompressed` and `fluidcompress_particlescompressed` - the number of fluid particles before and after compression.
    * `fluidcompress_volumesize` and `fluidcompress_volumet` - the original size and center of the fluid volumes.
    
For more information, see the [Fluid Compression|/fluid/compres
... (truncated, full doc is 5367 chars)
```

#### sop/flipmodifyvolume

```
#type: node
#context: sop
#internal: flipmodifyvolume
#icon: SOP/flipmodifyvolume
#since: 19.5

= FLIP Modify Volume =

"""Modifies a volume based on input volume or attributes. Used internaly in SOP based FLIP workflow."""

Modifies specified volume inside of a provided mesh or SDF. New volume values are either copied from a volume or mesh point attribute.

@parameters

Source Surface:
    #id: surfaceinput
    The specified volume is modified either inside of a geometry or a volume SDF provided at the second input.

Volume to Modify:
    #id: volume
    Name of the volume to be modified.

Input:
    #id: attributeinput
    Copy value from a point attribute or a volume. Can be automatically determined based on the existence of the volume specified with __Name__ at the second input.

Type:
    #id: attributetype
    Modify scalar or vector valued volume. Can be automatically determined based on the type of the VDB specified by __Volume to Modify__.

Name:
    #id: attributename
    Name of a point attribute or a volume to copy values from.

Scale:
    #id: scale
    Scale volume values.

Normal Value:
    #id: attributenormalvalue
    For scalar volumes, scaled signed distance function is added to the volume. For vector volumes, scaled normal direction is added to the volume. 

Additional Value:
    #id: attributevalue
    Value added to the volume.

Gradient Strength:
    #id: gradient_strength
    Strength of a gradient added to the volume.

Gradient Center:
    #id: gradient_center
    Center of a gradiet added to the volume.

Gradient Direction:
    #id:  gradient_dir
    Direction of a gradient added to the volume.

Gradient Offset:
    #id: gradient_dist
    Offset of a gradient added to the volume.    

Clip Gradient:
    #id: gradient_clip
    Only positive values of the gradient are added. Mainly used for setting up hydrostatic pressure that is zero in the air and in the water it linearly increases with depth.

Mode:
    #id: mode
    With __Override__ valu
... (truncated, full doc is 2507 chars)
```


---

## Ocean

### Topic Guides (ocean.zip)

#### ocean/index

```
= Oceans and water surfaces =
#bestbet: watersurface
#billboard: /images/billboards/ocean.jpg
#headerheight: 20vh

"""How to set up ocean and water surface simulations."""

@subtopics

== Shallow water solver ==

:: [/heightfields/shallowintro]
:: [/heightfields/shallowfields]
:: [/heightfields/shallowtrouble]
:: [/heightfields/shallowoutput]

== Oceans ==

:: [/fluid/oceans]
:: [oceanspectra]
:: [/fluid/sopwhitewater]
:: [/fluid/whitewater]

== Ripple solver ==

:: [ripplesolver]
:: [ripples]
```

#### ocean/oceanspectra

```
= Ocean spectra =

"""Spectrum wave types for ocean surfaces."""

== Overview ==

Houdini's [Ocean Spectrum|Node:sop/oceanspectrum] is a fast way to create highly-realistic and highly-customizable ocean waves. In Houdini 19.5, a new spectrum type was introduced, giving you more flexibility and possibilities.

The following chapters give you a short overview how to work with the most important spectrum parameters, and how they influence the wave pattern.

== Basic setup ==

A basic ocean surface requires three nodes. This setup can also seen as the basis for other simulations, for example [guided SOP FLIP fluid oceans|Link:../../fluid/sopoceanwaves]. More advanced setups, like the creation of large oceans with whitewater, are available through Houdini's [Ocean shelf tools|Link:../shelf/index#ocean].

# On _obj_ level, create a [Geometry|Node:obj/geo] node and dive into it.
# There, create a [Grid|Node:sop/grid] node. The grid acts as the ocean surface.
# Adjust the __Size__ parameter, e.g. to `10,10`.
# The __Rows__ and __Columns__ parameters define the ocean's resolution. Higher values reveal more details. Start with something between `300` for both values.
# Add an [Ocean Spectrum|Node:sop/oceanspectrum] node.
# Set __Resolution Exponent__ to `10` to increase the spectrum's quality and create more small waves. Together with the Grid's __Rows__ and __Columns__ you can control the ocean's final look.
# Add an [Ocean Evaluate|Node:sop/oceanevaluate] node.
# Connect the Grid to the first input, and the Ocean Spectrum to the second input.
# If the waves are too high, open the Ocean Spectrum's __Amplitude__ tab and dial down the __Scale__ parameter.

== Spectrum types ==

The Ocean Spectrum node provides two __Spectrum Type__ options: __TMA__ and __Phillips__. The new __TMA__ spectrum, added in Houdini 19.5, creates plausible and realistic results for a wide range of wind speeds and ocean depths. Two new parameters, __Swell__ and __Fetch (km)__, let you blend between choppy seas near the coast and typical open ocean waves. The second option represents the traditional spectrum waves, introduced in Houdini 12.5.

NOTE:
    The TMA (Texel-Marsen-Arlose) spectrum type is also known as _Encino_ waves. (Black)Encino is just the nickname of Christopher Horvath, who did the first implementation of this spectrum type for computer graphics. The Philipps spectrum's implementation is widely known as _Tessendorf_ waves.

NOTE:
    You can also set up two separate Ocean Spec... (truncated)
```

#### ocean/ripples

```
= Ripple Solver (DOP) =

== Overview ==

Houdini has tools for simulating the propagation of waves and ripples across a surface. This can be useful for simulating, for example, an ocean surface.

NOTE:
    Houdini 20 and higher provides a fast, OpenCL-based [Ripple Solver SOP|Node:sop/ripplesolver] with a slim UI and new posibilities. For more information, go to [Ripple Solver|Link:ripplesolver].

:video:
    #src: /videos/dynamics/ripple_height.mp4
    #autoplay: true
    #loop: true

The solver compares the "current" shape of the surface to a "rest" surface to determine which parts of the surface are "high" and "low", then uses that information to simulate ripple propagation.

Waves cannot be concave, since the solver only displaces points on the surface "up" and "down".

== Tools ==

The [Icon:DOP/rippleobject] [Ripple Object DOP|Node:dop/rippleobject] sets up a dynamics object for rippling. The [Icon:DOP/ripplesolver] [Ripple Solver|Node:dop/ripplesolver] sets up a dynamics object to be solved.

The [Icon:SOP/ripple] [Ripple surface node|Node:sop/ripple] deforms a grid to add concentric ripples. You can animate this node's parameters to "fake" simple ripples, or use it to set up the initial conditions for a true dynamics ripple simulation.

The [Icon:SOP/waveform] [Waveform tool|/shelf/waveform] deforms a surface into a wave shape with a direction. The Ripple solver has specific code to propagate waves created with this tool.

== How to ==

# Create a [Grid|/shelf/grid].

# Apply the [Ripple tool|/shelf/ripple] to deform the surface.

# In the network editor, [go into|/network/navigate] the grid's geometry object.

# Create a [Icon:COMMON/null] [Null node|Node:sop/null] branched off the initial [Icon:SOP/grid] [Grid node|Node:sop/grid] and name it `NULL_OUT`.

# Create another Null node after the ripple node and name it `RIPPLE_OUT`.

    [Image:/images/dynamics/ripple_sop_network.jpg]

# [Go back up|/network/navigate] to the Scene level and use the tab menu to create a [DOP network|Node:obj/dopnet].

# Go into the DOP network and create a [Ripple Object DOP|Node:dop/rippleobject]. In the parameter editor, set __Initial SOP Path__ to the path of the `RIPPLE_OUT` null (e.g. `/obj/geo1/RIPPLE_OUT`). Set __Rest SOP Path__ to the path of the `REST_OUT` null (e.g. `obj/geo1/REST_OUT`).

# Create a [Ripple Solver|Node:dop/ripplesolver] and [connect|/network/wire] the output of the Ripple Object node to the input of the Ripple Solver. Make sure the [display f... (truncated)
```

#### ocean/ripplesolver

```
= Ripple Solver (SOP) =

== Overview ==

The [Ripple Solver SOP|Node:sop/ripplesolver] is useful for creating ripples propagating on shallow water surfaces. For example, ripples caused by rain drops or bow waves created by a boat moving through water. It can also be used to generate cartoon-like effects on fabric or skin, pumping/breathing effects, and organic motion. The solver works best on flat geometry, but is also very reliable on 3D objects. 

[Image:/images/ocean/puddle_ripple.jpg]

There are two general approaches for creating ripples. However, it's also possible to combine both approaches.

* One method uses the difference between an object's original rest (_first_ node input) and deformed (_second_ node input) states. When using this method, the object's topology must not change: the number of points, vertices, and faces have to be _identical for the object's rest and deformed states_.
* Another method for creating ripples is to connect one or more collision objects to the solver's _third_ input. The object's position determines the ripples' originating point. Collision objects create impressions on the rest geometry. The object's scale also controls the size of the ripples' center. Collision objects can be static, moving, or deforming.

The node's _first_ input is mandatory. If the _second_ input is empty, because rest and deformed states are identical, the solver tries to use the object from the _first_ input. In this case you will see a warning.

NOTE:
    Currently, collision objects only create ripples, but waves aren't reflected from their surface to create complex patterns.
    
The ripple solver is similar to the [Shallow Water Solver SOP|Node:sop/shallowwatersolver]. However, the Shallow Water Solver is based on heightfields, while the Ripple Solver uses a geometry approach. It is important to note that, when using the Ripple Solver, collision objects can only create impressions. Bulged surfaces, for example from a submarine traveling below the water surface, aren't possible.

You can also choose from two __Wave type__ options: __Normal__ and __Vector__. With __Normal__, the points are only displaced along the object's normals. Additionally, the solver's `displacement` point attribute is scalar and stores a point's current distance from the rest position. With __Vector__, there's no such restriction and the `displacement` attribute is a vector. To see the `displacement` attribute's value, open the solver's __Output__ tab and turn on __Di... (truncated)
```

### Ocean SOP Nodes

#### sop/oceanspectrum

```
= Ocean Spectrum =

#type: node
#context: sop
#icon: SHELF/wave
#internal: oceanspectrum
#since: 12.5

"""Generates volumes containing information for simulating ocean waves."""

This node creates volumes containing information modeling the effect of constant wind and tidal pull on ocean waves over time. You can then wire into the [Ocean Evaluate node|Node:sop/oceanevaluate] to animate ocean surface geometry.

Specifically, this node generates three named volumes that [Ocean Evaluate|Node:sop/oceanevaluate] expects in its second input.

`phase`:
    The phase offset of each wave.

`frequency`:
    The angular frequency of each wave.

`amplitude`:
    The amplitude of each wave.

The `amplitude` volume primitive will have additional attributes created that control behavior of the ocean when evaluated, for example the __Chop__ and __Time Offset__ parameters.

Multiple ocean spectra can be layered together by [Merging|Node:sop/merge] them together before sending them into [Ocean Evaluate|Node:sop/oceanevaluate] for geometry deformation, or for render-time evaluation via the [Ocean Sample Layers|Node:vop/oceansamplelayers] VOP.

This node also accepts a world-space Houdini or VDB volume to use as a suppression or contribution mask when the ocean is evaluated to further modify the ocean amplitude, as well as multiplying in evolving noise to break up tiling and mimic wind-over-water effects.  Additionally, any non-volume points plugged into the inputs will be used to "instance" ocean waves onto the deformed geometry with position and orientation controlled by the [Copying and Instancing|/copy/instanceattrs] attributes on the input points and the randomized parameters on the __Wave Instancing__ tab of this node.

NOTE:
    If the camera is quite close to the ocean surface, there may be some visible blocky artifacts. To fix this you can either zoom out or increase the __Resolution Exponent__ slightly (to 10 or 11).

@parameters

Resolution Exponent:
    The resolution expon
... (truncated, full doc is 14615 chars)
```

#### sop/oceanevaluate

```
= Ocean Evaluate =

#type: node
#context: sop
#icon: SHELF/wave
#internal: oceanevaluate
#version: 2.0
#since: 16.0

"""Deforms input geometry based on ocean "spectrum" volumes."""

This node uses volumes generated by one or more [Ocean Spectrum|Node:sop/oceanspectrum] nodes [Merged|Node:sop/merge] together and connected to the second input to deform geometry in the first input.  If multiple ocean spectra are input, their waves will be added together during evaluation, possibly modified by any mask or noise parameters on each input __Ocean Spectrum__ layer.

@parameters

Time:
    The time at which to evaluate the ocean surface.

Downsample:
    Downsample the incoming ocean spectra before evaluating any ocean values.  This parameter specifies the number of powers of two to remove from the resolution of the incoming ocean spectrum. For example, if the spectrum was originally specified at resolution 10 to generate a 1024 x 1024 volume, downsampling by 2 will evaluate ocean volumes at resolution 8, a 256 x 256 volume.

    TIP:
        The same high resolution spectrum can be processed by multiple Ocean Evaluate nodes, for example one with no downsampling to deform surface geometry, and another at a downsampled resolution to generate the more expensive volume or point output.

Max Resolution:
    Downsample the incoming ocean spectra to the specified maximum resolution before evaluating any ocean values.  This parameter is useful to avoid evaluation of very high-resolution spectra when only requiring simulation data, for example.  It can also be more convenient than the __Downsample__ parameter when there are multiple incoming spectra of different resolutions.

Depth Falloff:
    Specifies how deformation and velocity values falloff as the input points lie below the ocean surface.  This value also controls the rank of the calculation volumes that are output if __Rest Displacement__ or __Rest Velocity__ is enabled: 2D if falloff is __None__ but 3D otherwise.

    None:
... (truncated, full doc is 11157 chars)
```

### Ocean LOP Node

#### lop/karmaocean

```
= Karma Ocean =
#type:     node
#context:  lop
#internal: karmaocean
#icon:     LOP/karmaocean
#status:   deprecated
#since:    19.5
#index:    no

"""Render an ocean with the Karma CPU renderer."""

:warning:Deprecated:
    The __Karma Ocean LOP__ is now deprecated. Use the [Houdini Procedural: Ocean LOP|Node:lop/houdinioceanprocedural].

== Overview == (overview)

Render an ocean using the Karma CPU renderer, often created by the [Small|/shelf/smallocean] or [Large|/shelf/largeocean] Ocean shelf tools.


== How to ==

# On the __Oceans__ shelf, click __Small Ocean__.

# Dive into the `ocean_geometry` node. The shelf tool automatically creates a Karma Ocean node.

# Save the project.

# Select the  `save_spectra` [Geometry Output node|Node:out/geometry].

# Set __Valid Frame Range__ to __Render Frame Range__ and turn on __Save to Disk (
in Background)__ to cache the scene.

# Do the same with the [File Cache|Node:sop/filecache] node named `bake_foam`.

# Connect the File Cache node's output to the [Merge|Node:sop/merge] node's (`merge_foam`) 
input. When you move the timeline slider, foam should be visible in the viewer.

# Switch to the `/stage` network and select the Karma Ocean node.

# Turn on __Foam File__. The correct path should already be shown.

# For faster iterations, set __Dicing Quality__ to `0.25` and turn off __Interior Geometry__.

# Add an [Environment|Node:lop/domelight] light node.

# Connect the Karma Ocean node's output to the light's input.


== Tips == (tips)

* When using the [Small:/shelf/smallocean] or [Large:/shelf/largeocean] Ocean shelf tools inside the Solaris `/stage` context, the ocean proxy and render geometry will be created within the Karma LOP itself, keeping all components within Solaris.

* After changing the parameters on the [Ocean Spectrum|Node:sop/oceanspectrum] SOP(s) that generate the ocean spectrum, you will need to re-save the spectra to a file for Karma to pick up the changes. If Karma is currently rendering in the Sol
... (truncated, full doc is 5717 chars)
```


---

## Particles (DOP)

### Topic Guides (dopparticles.zip)

#### dopparticles/index

```
= Particles =

"""How to create particle simulations."""

Particles are extremely useful for realistically modeling phenomena such as flocking, smoke, fire, and dust. 

Particles in the dynamics environment are multi-threaded and memory efficient. They also provide extensive artist control, since they are built out of VOPs.

@subtopics

== Getting started ==

:: [emitting]
:: [network_flow]

== Behavior ==

:: [forces]
:: [react]
:: [speedlimit]
:: [follow]
:: [filaments]
:: [visualize]
:: [collisions]

== Next Steps ==

:: [instancing]
:: [Sprites|/shelf/dynamics_popsprite]

== Reference ==

:: [streams]
:: [vexpressions]
:: [attributes]
:: [tips]



```

#### dopparticles/attributes

```
= Attributes =

A particle system is first and foremost driven by attributes. Here are some of the attributes understood by the solvers.

The attributes are listed with the `@` style prefix to give the full type. No prefix means float.

There are two suggested methods for creating attributes: [POP VOP|Node:dop/popvop] and [POP Wrangle|Node:dop/popwrangle]. 

In a  [POP VOP|Node:dop/popvop], you can use a [Bind Export VOP|Node:vop/bind] to write out your desired attribute. 

In a [POP Wrangle|Node:dop/popwrangle] you can use a prototype to specify the attribute and default.

{{{
int @id = -1;
point @orient = {0, 0, 0, 1};
}}}

NOTE:
    The expression after the equals must be a simple constant expression.

@attributes

Houdini will use the `Cd` (diffuse color) point attribute to color particles.

== State ==

`age`:
    #type: float
    
    Time in seconds since the particle was born. To get the relative time, useful for fading effects, use `@nage`.
    
`nage`:
    #type: float
    #readonly: yes
    
    `@age` divided by `@life`. Implicit attribute, you cannot write to this.
    
`life`:
    #type: float
    
    Time in seconds the particle is allowed to live. When `@age>@life`, the particle will be marked dead.
    
`id`:
    #type: int
    #default: -1.
    
    A unique id for the particle that remains the same throughout a single simulation. Always use `@id` rather than `@ptnum` to avoid things changing when particles are deleted. Use `findattribval()` to look up the point number that corresponds with an id.
    
== Linear Physics ==

The particle solver uses the standard `v` (velocity) attribute as the direction of the particle. Use `length(@v)` to get the speed of the particle.

`force`:
    #type:
    
    Forces on the particle for this frame.
    
`mass`:
    #type: float
    #default: 1.0
    
    Inertia of the particle.

`spinshape`:
    #type: vec3
    #default: (1, 1, 1)

    This is multiplied by `@pscale` to determine the rough shape of the particle for the purpose of rotational inertia.

`drag`:
    #type: float
    #default: 1.0
    
    How much the particle is dragged by any wind effects.
    
`dragexp`:
    #type: float

    A value from 1 to 2. An exponent of 1 means that a particle is dragged to the wind velocity by an amount proportional to the difference in speeds. A value of 2 makes it the square of the speeds. The latter causes fast moving particles to be crushed faster, and has less influence on particles already near the wi... (truncated)
```

#### dopparticles/collisions

```
= Collisions =

There are three different places you can set POP Collisions. You can use the __Collision Behavior__ tab on the [POP Solver DOP|Node:dop/popsolver], the [POP Collision Behavior DOP|Node:dop/popcollisionbehavior] node, or the [POP Collision Detect DOP|Node:dop/popcollisiondetect] node. Depending on what you want to accomplish, you can set up collisions using any of the following:

POP Solver DOP:
        Use the __Collision Behavior__ tab on the POP Solver for doing simple RBD collisions. Particles will bounce by default, but you can also set them to die, stop, stick, or slide.
        
POP Collision Behavior DOP:
        Use POP Collision Behavior when you want the particles to do more than one action. For example, have some particles bounce, some stick, and some slide.

POP Collision Detect DOP:
        Use POP Collision Detect when you don't necessarily want to change the behavior of the particles, but gather information such as when particles hit, where they hit, what their velocity was when they hit, etc. 
        
        You could also use this node to generate attributes that can be applied to specific particles. For example, when particles hit a surface, make them turn red.
```

#### dopparticles/emitting

```
= Emitting =

There are two main way to create particles: from geometry or from a point in space. There are tools on the __Particles__ tab of the [shelf|/shelf/] that let you create particle systems. Clicking the [Icon:POP/location][Location|Node:dop/poplocation] button will allow you to select a point in space from which to emit particles, and the [Icon:POP/source][Source|Node:dop/popsource] button will allow you to choose a geometry object from which to emit particles.

In addition to these common ways to create particles, you can also create new particles from existing particles using the [Icon:POP/split][Replicate|/shelf/dynamics_popreplicate] tool.

:vimeo:Emitting particles
    #id: 113730728

== How to use the shelf tools ==

For more information on how to emit particles, see the following help pages:

[Icon:POP/fireworks] |
    [Fireworks|/shelf/dynamics_popfireworks] |
        Emits multi-colored particles from a point, which simulates fireworks.

[Icon:POP/location] |
    [Location|/shelf/dynamics_poplocation] |
        Emits particles from a point in all directions.

[Icon:POP/source] |
    [Source|/shelf/dynamics_popsource] |
        Emits particles from an object in all directions.

[Icon:POP/split] |
    [Replicate|/shelf/dynamics_popreplicate] |
        Generates particles from incoming particles.

```

#### dopparticles/forces

```
= Applying forces =

You can direct particle motion with forces. Forces can emanate from [geometry|/model/create] in the scene (for example, you can create a [sphere|/shelf/sphere] and have it attract or repel particles), or you can create a general directional force (such as gravity).


== How to direct particle motion with forces ==
    
:task: Make geometry attract or repel particles:

    # Click the [Icon:SHELF/pointattract][Point Attract|/shelf/dynamics_popattract] or [Icon:SHELF/curveattract][Curve Attract|/shelf/dynamics_popattract] button from the __Particles__ tab of the [shelf|/shelf/].  
    # Select the particle system you want to be attracted or repelled and press ((Enter)) to confirm your selection.       
    # Select the object or curve you want the particles to be attracted to or repelled from and press ((Enter)) to confirm your selection.
    The degree of attraction/repulsion can be modified with the __Force Scale__ parameter on the __Force__ tab of the [POP Attractor DOP|Node:dop/popattract] node. A positive value will attract the particles and a negative value will repel the particles.
    
    [Image:/images/shelf/POPattract.jpg]

:task: Create a general directional force:

    # Click the [Icon:POP/force][Force Particles|/shelf/dynamics_popforce]  tool on the __Particles__ tab of the shelf.     
    # Select the particle system you want to be affected and press ((Enter)) to confirm your selection.      
    # Set the __Force__ parameter on the [POP Force DOP|Node:dop/popforce] node to affect the particles. By default this is set to `-9.81` in the Y direction, to apply a gravity force.
    
    [Image:/images/shelf/POPforce.jpg]
        
    NOTE:
        You can also use the [Icon:POP/fan][Fan Particles|Node:dop/popfan] or [Icon:POP/wind][Wind on Particles|/shelf/dynamics_popwind] shelf tools, depending on how you want the particles to react to the directional force.
    
:task: Add random force to particles:

    # Click the [Icon:POP/force][Force Particles|/shelf/dynamics_popforce] tool on the __Particles__ tab of the shelf.     
    # Select the particle system you want to be affected and press ((Enter)) to confirm your selection.       
    # Modify the parameters on the __Noise__ tab of the [POP Force DOP|Node:dop/popforce] node. You can change the __Swirl Size__, __Pulse Length__, __Roughness__, __Turbulence__, etc,

:task: Move particles along, toward, or around a curve:

        # Create a curve using the [Icon:SOP/curve.svg... (truncated)
```

#### dopparticles/instancing

```
= Instancing and Rendering =

== Instance geometry on particles ==

:task: Instance geometry on particles:
        # Select the [particle system|/dopparticles/] you want to be affected.    
        # Click the [Icon:POP/instance][Instance Geometry on Particles|Node:dop/popinstance] shelf tool on the __Particles__ tab.       
        # Select the object you want the particles to be replaced with and press ((Enter)) to confirm your selection.
        
        [Image:/images/dopparticles/torque1.jpg]
        
        For specific parameter help see the [Icon:POP/instance][POP Instance DOP|Node:dop/popinstance] node help.

:task: Rotate the instanced geometry using torque:

        # Insert a [POP Torque DOP|Node:dop/poptorque] node into your chain.

                Torque is like sticking a handle on something and rotating it by pushing on the handle.

                [Image:/images/torque.png]

        # Set the desired __Axis__ to spin the particle around, and the __Amount__ of speed.
        
:task: Make the instanced geometry look at an object:
        # Insert a [POP Look At DOP|Node:dop/poplookat] node into your chain.
        # Set the __ Mode__ to __Target is Point__.      
        # Set the __Reference Object__ for the particles to look at.  1The objects align in the direction of the reference object during the simulation.
    
                [Image:/images/dopparticles/torque2.jpg]
                
                NOTE:
                        If no reference object is used, the particles will look at 0, 0, 0. You can modify the __Target__ parameter to change its location.

:task: Make the instanced geometry look at a plane:
        # Insert a [POP Look At|Node:dop/poplookat] node into your chain.
        # Set the __ Mode__ to __Target is Direction__. 
        # Set the __Target__ parameter to where you want the particle to reorient to face. In the image below, __Target__ is set to `0.5,0,1`.
    
        [Image:/images/dopparticles/torque3.jpg]
        
== Rendering Instanced Geometry ==(render)

When you create a particle system, Houdini also creates a renderable object at _obj_ level. For example, if you create a particle system with the [Icon:POP/location][Location Particle Emitter|/shelf/dynamics_poplocation] shelf tool, your renderable object will be called `location_particles`.

# In order to render instanced geometry, append an [Instance SOP|Node:sop/instance] after the [DOP Import Fields SOP|Node:sop/dopimportfield] node inside the render... (truncated)
```

#### dopparticles/tips

```
= Tips =

* Click the __Hidden__ flag to hide all the geometry created by that node, which is similar to turning off the __Guide__ flag in the old POPs.

* Click ((MMB)) on a DOP node to see how many points are in that node, and also what attributes are present. This is helpful when writing [VEXpressions|vexpressions].

* Click ((RMB)) on a POP node to access the __Spreadsheet__. You can choose to __Hide All Attributes__ in the __View__ dropdown menu, and then select the particular ones you want information about, such as color or position. Pressing play will give you live updates in the spreadsheet.

* To fix the problem of banding when dealing with strong forces, change the __Jitter Birth Time__ on the [POP Source|Node:dop/popsource] from __Positive__ to __Negative__.
        
[Image:/images/dopparticles/banding1.jpg]
```

#### dopparticles/vexpressions

```
= Writing particle VEX expressions =

== Background ==

A powerful and much used feature of the pre-Houdini 13 particle workflow was _local variables_.
Local variables allowed almost any parameter on a particle node to vary per-particle.

In the new dynamics particle workflow, these kinds of expressions are replaced with _VEX expressions_.
VEX expressions attempt to address the following problems with the old local variables:

* Local variables were slow (compared to VEX).

* Local variables were single-threaded. It was possible to write threadable expressions, but many of the common expression functions were not threadsafe, causing the whole system to fall back to single-threaded behavior.

* The mapping of attributes to local variables was idiosyncratic and obscure (for example, using local variable `$CR` to access the attribute value `Cd.x`).

* Local variables were difficult. Some things were simple, For example, `rand($ID)`. However, for more complicated expression things started to break down quickly. Also, if you wanted to set a number of parameters based on a common evaluation, you had to use spare parameters as helpers.

== Using VEX in particle nodes ==

In the parameter interface of nodes that support VEX expressions, each block of parameters has a __Use VEXpressions__ checkbox.

* If the checkbox is off, the parameters use the normal Houdini expression language, but _those values cannot vary per-particle_.

* When this checkbox is on, a multi-line editor appears where you can write a snippet of VEX code to evaluate on each particle at each time step.

VEXpressions were not meant to replace VOPs, they were meant to augment it.

The `@` in the VEX syntax is meant to stand for attribute. Houdini uses the `@` syntax in groups already. This was modified for VEX, because there was no way of determining the attribute was a vector, float, integer, or string. Prefixing with `v@` will define the type as a vector, `i@` will define the type as an integer, and `s@` will define the type as a string. 

== Tips ==

* When you're editing in the multi-line editor you can press ((Ctrl + Enter)) to "commit" the changes and update Houdini.

* Each multi-line editor has a drop-down menu containing useful pre-made VEX snippets. The menu has a `Pass through` item which simply fills in the names of the parameters in the block assigned to themselves (for example `wind = wind;`). This may be useful as a starting point from writing your own code to override the parameter ... (truncated)
```

### Key Particle SOP Nodes

#### sop/particle

```
#type: node
#context: sop
#internal: particle
#icon: SOP/particle

#tags: particles

= Particle =

"""Creates simple particle simulations
without requiring an entire particle network."""

This node lets you set up a simple particle network quickly, without
having to create a [particle network|Node:sop/popnet] and
[particle nodes|/nodes/pop/].

While you can't create simulations
anywhere near the complexity of a real particle network, you can
easily create simulations that are very common and useful, such as
snowfall or sparks, as well as very interesting deformations.

This node lets you:

- Birth points from the points in the geometry connected to
  its first input and simulate them as if they were particles,
  _OR_
  move the points of the input geometry as if they were particles. 
  
  The first input *must* be connected for the node to work.
  
- Add an external force (like gravity) in one direction, and
  a wind (pushes particles up to but not beyond a certain speed)
  in another direction.
  
- Connect collision geometry to the second input to have the
  particles bounce off it.
  
- Set particles to either bounce off of, or die at,
  a bounding box.

Particles have various attributes that regular geometry does not have,
such as: _velocity_, _life expectancy_ and _age_. These attributes are
carried with each point in order to carry out the simulation.

NOTE:
        __Remove Unused Particles__ checkbox must be turned to remove particles if you set the __Hit Behavior__ to __Die on Contact__.

@inputs
    Particle Source:
        Any geometry with points, e.g. polygon sphere, mesh.
        The points in this geometry become particles.

    Collision Object:
        This input defines an object for the particles to collide with.
        When this happens, the particles can either die, stick or
        bounce, or spawn new particles. It is important to note that
        when the collision object is deforming, collision detection may
        fail, causing some part
... (truncated, full doc is 6404 chars)
```

#### sop/particletrail

```
#type: node
#context: sop
#internal: particletrail
#icon: SOP/particletrail
#since: 19.0

= Particle Trail =

"""Generates trails from the incoming particles that can be used to render sparks, fireworks, and rain."""

:video:
    #src: /videos/pyro/sparkler.mp4

== Overview == (overview)

    The [Particle Trail SOP|Node:sop/particletrail] takes an animated particle system and generates motion trails from its particles. These trails can be used for various effects such as sparks, fireworks, and rain. This node also allows you to control the look of the trails. This enables you to fine-tune their look in the SOP context, without the need to render the points with large amount of motion blur.
    
    Particles from simulation and the generated particle trails.
    :compare_images:
        #image1: /images/sop/particletrail.png
        #image2: /images/sop/particles.png
    
    In addition, the Particle Trail node can generate split trails to mimic the look of bursting sparks or splashing rain. The generated splits are only approximations of the real physical behavior you could achieve with a particle simulation. Using this node has the benefit of providing faster iteration times without the need of complex particle simulation setups, while giving you more directable controls over the splits.
    
    Particle trails with and without splitting enabled.
    :compare_images:
        #image1: /images/sop/particletrail_split.png
        #image2: /images/sop/particletrail_nosplit.png
    
    NOTE:
        This node uses in-between frames to sample the motion trails, but does not perform any interpolation between integer frames. Therefore, you have to make sure its inputs can evaluate on fractional frames. DOP networks do not use the `id` attribute to match particles from different frames, so it will produce incorrect interpolation when particles die out. 
        
        You can use the __Quick Setups__ menu to append a [Time Blend SOP|Node:sop/retime] before the Partic
... (truncated, full doc is 28208 chars)
```


---

## Volume / VDB

### Key Volume SOP Nodes

#### sop/volume

```
#type: node
#context: sop
#internal: volume
#icon: SOP/volume

#tags: create, model

= Volume =

"""Creates a volume primitive."""

The Volume SOP creates a volume primitive.  A volume is a box divided
up grid of smaller boxes, called voxels, each of which can store a
number.  The resulting primitive can be used to define a scalar field
over a volume sampled at the grid centers.

The grid generated by the Volume SOP has constant value everywhere.
It can be further manipulated on a voxel-by-voxel basis using the
Volume VOP SOP or the Volume Mix SOP.

When mantra renders volumes it overrides rendering parameters
according to the name of the volume.  This name can be set in the
Volume SOP (or later using the [Name SOP|Node:sop/name]).  The name is also used for
the default bindings to the [Volume VOP SOP|Node:sop/volumevop].

The Volume SOP can also generate sets of volumes.  Selecting a rank of
Vector will create three volumes suitable for a velocity field, a rank
of Matrix will create nine volumes suitable for a strain tensor field.

TIP:
    If you connect geometry to the Volume SOP's input, it will create a
    bounding box around the input geometry 

@parameters
    Rank:
	Each volume primitive only holds a single number per voxel
	cell.  If you want to use higher order volumes, such as vector
	fields or matrix fields, you can use multiple volume
	primitives.  The __Rank__ option lets you create multiple named
	volumes to match vector or matrix fields.

    Name:
	If not blank, the created volume primitive will have the name
	primitive attribute set to this value.  Naming volumes allows
	mantra and the [Volume VOP|Node:sop/volumevop] to override the correct parameters
	with the values of the volume.  If the created volume is
	Vector or Matrix, .x or .xx will be appended to identify the
	subcomponents.

    Initial Value:
	The created volume primitive will have the same value
	throughout the volume.

    == Dimensions ==

	== Center/Size ==
	    Size:
		The size of
... (truncated, full doc is 11022 chars)
```

#### sop/volumewrangle

```
= Volume Wrangle =

#type: node
#context: sop
#internal: volumewrangle
#icon: SOP/volumewrangle
#tags: volume, attrs, core, tech
#since: 12.5

"""Runs a VEX snippet to modify voxel values in a volume."""

== Overview ==

This is a very powerful, low-level node that lets experts who are
familiar with VEX tweak voxel values using code.

This node corresponds to the [Volume VOP SOP|Node:sop/volumevop],
but uses a textual VEX snippet instead of a VOP network.

This node runs the snippet _on every voxel in the input volume(s)_
(unless the __Bind each volume to density__ parameter is on).
The snippet can edit the input geometry by changing attributes.
It can access information from other geometry using attributes and VEX functions.

* Press ((MMB)) on the node to see any error output from the snippet.

* You can use the VEX function `ch` to evaluate parameters.
  The path is relative to this node (`ch("parm")` will evaluate the parameter `parm` on this node).
  This evaluation will be done at the current time.

* Unlike the [Volume Mix SOP|Node:sop/volumemix], this does not use local variables.
  Further, all backtick expressions and `$F` variables will be evaluated at frame 1,
  not the current time.
  Use `Frame`, `Time`, or `TimeInc` instead.
  
* The [Volume VOP|Node:vop/volume] only processes voxels to write to (and only once for each colocated voxel).


== Syntax ==

:include wrangle_syntax:


== Reading and modifying the voxel value == (values)

The current voxel value in a volume is available as `@<<volume_name>>`.
You can read this variable to get the current value, and assign it to change the value.
For example, to add `0.1` to the value of every voxel in the float volume `foo`:

{{{
#!vex
@foo += 0.1
}}}

If a volume does not have a name, it will automatically be bound to `@density`.

If you have multiple named volumes in the input, you can write a single snippet
that modifies the different volumes in different ways, for example:

{{{
#!vex
@foo += 0.1
@bar += 
... (truncated, full doc is 7893 chars)
```

#### sop/volumerasterizeparticles

```
= Volume Rasterize Particles =

#type: node
#context: sop
#internal: volumerasterizeparticles
#icon: SOP/volumerasterizeparticles
#tags: volumes, merge
#since: 13.0
#verb_since: 16.5

"""Converts a point cloud into a volume."""

The Volume Rasterize particles operation takes a cloud of points and fills
a volume accordingly. If the input volume has more than one named
primitive, the named volumes will be filled with data from point attributes
that match the name of the volume. Currently only VDB vector volumes
support filling from vector point attributes.

The point attribute `pscale` is used (along with the specified __Coverage
Attribute__) to control the generated volume.

This is a highly specialized node designed for filling the volume
as fast as possible, so a lot of the controls present in [Volume Rasterize
Points|Node:sop/volumerasterizepoints] are not available.

Filtering is automatically performed to ensure small particles will always
contribute to the resulting volume.  This means that when you rasterize to a
particularly low resolution volume, things will seem to fatten.

The `volumefilterstochastic` integer primitive attribute can be used to
override how points are filtered to voxels. For fields that can't be
meaningfully averaged together, setting this attribute to a value of 1 on
that volume primitive will cause only one of the overlapping particles to
contribute to each voxel, avoiding any averaging. This parameter only
applies to fields other than coverage.

Alternatively, the stamping method for each volume can be controlled separately
by specifying rules, bypassing the need to set primitive attributes.

NOTE:
    This node does not support rasterizing into tapered volumes.

@parameters

Destination:
    Which volumes or VDBs in the first input to stamp into.

Particles:
    A group of points in the second input to rasterize.

Filter:
    The filter shape to use when splatting particles. The default Gaussian
    filter will produce smooth blobs and 
... (truncated, full doc is 5881 chars)
```

#### sop/volumemix

```
#type: node
#context: sop
#internal: volumemix
#icon: SOP/volumemix

#tags: volumes, merge

= Volume Mix =

"""Combines the scalar fields of volume primitives."""

The Volume Mix operation manipulates the scalar data associated with
volume primitives. For each pair of volume primitives in the source
group and the mix group, the given calculation is performed and the
results stored in the source group's primitive. Note that the volumes do
not need to have the same orientation or resolution, the second volume
will be sampled at the orientation and resolution of the first volume.

The copy mode allows you to resample a volume into a different
resolution or orientation.

@parameters
    Source Group:
        The volume primitives to be used from the first input.
    Mix Group:
        The volume primitives to merge in from the second input.  If
        there is no second input, this group will be found from the
        first input.
    Mix Method:
        Each voxel of each volume primitive in the source group will be
        mixed with the corresponding voxel of the corresponding volume
        primitive of the mix group according to this mix method. A
        refers to the first input's value, B refers to the second
        input's value. If there is no second input, B will be found
        from the corresponding volume of the first input.

	Copy:
	    result = B
        Add:
            result = A + B
        Subtract:
            result = A - B
	Diff:
	    result = abs(A - B)
        Multiply:
            result = A * B
        Divide:
            result = A / B
	Invert:
	    result = -A
        Max:
            result = max(A, B)
        Min:
            result = min(A, B)
        Clamp:
            result = clamp(A, rangemin, rangemax)
        Blend:
            result = A * (1-blend) + B * blend
        User:
            result = Value Expression
    Range:
        Defines the range to which the volume's voxel values will be
        clamped when the mix method is
... (truncated, full doc is 4069 chars)
```

#### sop/volumeresample

```
#type: node
#context: sop
#internal: volumeresample
#icon: SOP/volumeresample
#since: 11.0
#verb_since: 16.5

#tags: volumes, merge

= Volume Resample =

"""Resamples the voxels of a volume to a new resolution."""

The Volume Resample operation resamples the voxels of a volume to a
new resolution.

This is similar to scaling an image in COPs, so similar filtering
operations are provided.

NOTE:
    The volume bounding box will be unchanged by this operation. This means that unless the new resolution is an integer multiple of the old, the resulting voxels may no longer be square.

:include no_vdb:

@parameters
    Source Group:
        The volume primitives to be resampled.
    Filter:
        Specifies the type of filter to use when scaling. The __Box__ filter
        is the fastest. The __Gaussian__ is typically the best choice for most uses. __Catmull__ is used when you need something a bit sharper than Gaussian.
    Filter Scale:
	The default scale is set to properly capture the information
	in the original volume.  Increasing this results in a blurring
	effect and decreasing may cause it to start to ignore incoming
	voxel information.

    Specify Exact Resolution:
	The final voxel resolution may either be computed from the
	size of the box or set as a ratio to the incoming resolution.

    Uniform Sampling:
	This parameter controls which axis is divided into __Uniform
	Sampling Divs__.

    Uniform Sampling Divs:
	The number of voxels to divide the __Uniform Sampling__ axis into.
	The other axes will be divided into the number of cells that
	fit for this voxel size.

    Sampling Divs:
	When using non-uniform voxel cells, each dimension's resolution
	can be specified here.

    Div Size:
	The uniform size of the voxels, when specifying the voxel size
	directly.  The given sized box will be filled by voxels of
	this size.

    Resolution Scale:
	The ratio of the original resolution to use.  2.0 will result
	in twice as many voxels in each dimension, for a total 
... (truncated, full doc is 2433 chars)
```

#### sop/volumenoisefog

```
#type: node
#context: sop
#internal: volumenoisefog
#icon: SOP/volumenoisefog
#since: 19

= Volume Noise Fog =

"""Adds or generates noise in volume/VDB primitives."""

== Overview ==

The Volume Noise Fog SOP provides a simple interface for quickly adding coherent noise to voxel values, reducing the need to create VOP networks or write VEX code. All of the models provided by the [Unified Noise VOP|Node:vop/unifiednoise] and [Cloud Noise VOP|Node:vop/cloudnoise] can be used with this node.

@parameters

~~~ General ~~~
    #id: linkgeneral
  
    Mask:
        #id: maskweight
        When turned on, uses the blend between the original input volume (given by __Fog Volume Name__) and the modified volume by this node.
        
    Invert Mask:
        #id: invertmask
        Reverses the mask that blends between the original input volume (given by __Fog Volume Name__) and the modified volume by this node.
        
    Mask Volume Name:
        #id: maskvolumename
        The name of the fog volume to mask this node’s effect.
        
    Fog Volume Name:
        #id: vol
        The name of the volume primitive to modify with noise.
      
~~~ Noise Value ~~~
    #id: linknoisevalue

    Operation:
        #id: operation
        Specifies how to combine the generated adjustment value with the incoming volume. If the target primitive does not exist on the input geometry, all operations will have the same effect.
            
        Set:
            Use this operation if you want to overwrite any existing value with the generated adjustment value.

        Add:
            The generated adjustment value will be added to the existing volume primitive.

        Subtract:
            The generated adjustment value will be subtracted from the existing volume primitive.

        Multiply:
            The existing volume primitive value will be multiplied by the generated adjustment value.

        Minimum:
            Output will be minimum of the existing volume primitive v
... (truncated, full doc is 8487 chars)
```

#### sop/volumesurface

```
#type: node
#context: sop
#internal: volumesurface
#icon: SOP/volumesurface
#since: 11.0

#tags: volumes, merge

= Volume Surface =

"""Adaptively surfaces a volume hierarchy with a regular triangle mesh."""

The Volume Surface operation surfaces a volume hierarchy with a regular
triangle mesh.

The volumes in the first input are grouped together into a hierarchy.  There
should be a root volume that contains all of the other volumes.  Each point is
then evaluated by taking the value of the innermost volume, possibly blending
to the exterior values if overlap is specified.

If there is no second input, the curvature of the mesh is used to control the
edge length of the surfacing.  If there is a second input, it is treated as a
volume hierarchy whose scalar values are the desired edge lengths.  

NOTE:
    The [Volume Feather SOP|Node:sop/volumefeather] is useful to ensure there are no sharp changes in edge lengths that can confuse the surfacer.

Surfacing is done by growing from a seed point.  As a result, only one
connected component of the volume will be surfaced.  Further, if there are
topological handles (such as a mug or torus) these will not be fused together.

Ideally a signed distance field is used for the surfacing.  In any case, a
valid gradient should be present for a sufficient distance around the desired
surface to allow the point-settling to succeed.

This SOP is similar to [Particle Fluid Surface|Node:sop/particlefluidsurface] since both create a surface over either a volume or particles; however, they are used for different purposes. The Volume Surface SOP is intended for static objects and create one surface over all volumes, whereas Particle Fluid Surface is intended for objects that have motion and create separate surfaces over individual clusters. For example, the Volume Surface SOP can be used to simulate a ski trail on a mountain, and the Particle Fluid Surface could be used to simulate a river.

:include no_vdb:

@parameters

Source Group:
    
... (truncated, full doc is 6011 chars)
```

#### sop/volumevelocity

```
#type: node
#context: sop
#internal: volumevelocity
#icon: SOP/volumevelocity
#since: 12.0

#tags: volumes

= Volume Velocity =

"""Computes a velocity volume."""

The Volume Velocity operator adds a procedural velocity field to the input
volumes.  Three volumes together define a velocity field, one for each of the x, y, and z components.  The [Volume SOP|Node:sop/volume] can be used to create three properly named volumes using the Vector option.

@inputs

Velocity Volumes:
        The volume primitives to add a velocity field to.
Points:
    Points to sample velocity values from.
Mask:
    The velocity will be zeroed out outside this masked area.

@parameters

Group:
    The volumes to add to.  The first three are the x, y, and z components
    respectively for adding velocity values to.

Add Uniform Velocity:
    Controls whether a constant velocity will be added or not.
    
Constant Velocity:
    A uniform velocity added everywhere in the velocity field.

== Vortex ==

Add Vortex:
    A vortex field is a velocity field that spins around an axis, like a
    spinning tornado.
    
Center:
    The origin of the spinning vortex.
    
Direction:
    The axis around which the velocity field will spin.
    
Angular Velocity:
    How fast the velocity field spins.  This is how fast the velocity field
    will be one unit away from the center.
    
Vortex Radius:
    Instead of having the vortex affect the entire space, it can be
    constrained to only operate in a tube around the axis.  This is the
    radius of that tube.
    
Vortex Ramp:
    To avoid a sudden change in velocity at the edge of the vortex, this
    ramp describes a speed multiplier of the vortex from the center to the
    edge of the vortex.

== Curl Noise ==

Add Curl Noise:
    Curl noise is a special type of noise that describes a velocity field
    that doesn't contract or expand.  Particles that move through
    it will keep a uniform density.
    
Scale:
    Strength of the noise field.
    
Swi
... (truncated, full doc is 5225 chars)
```

#### sop/volumevisualization

```
#type: node
#context: sop
#internal: volumevisualization
#icon: SOP/volumevisualization
#since: 11.0
#verb_since: 16.5

#tags: volumes, merge

= Volume Visualization =

"""Adjusts attributes for multi-volume visualization."""

The Volume Visualization operator adds detail attributes to its input geometry
that tell the viewport how to render sets of multiple volumes. For example, you
may want to take a density volume and color it according to three separate
`Cd.x`, `Cd.y`, and `Cd.z` volumes.

There are two major components to the viewport volume visualization.

First there is the opaque smoke. This smoke occludes geometry behind it and can
also cast shadows on itself from light sources. Finally, a diffuse color can be
specified for what light colors it reflects rather than absorbs.

NOTE:
    A density of 1 means a density of 1 unit of smoke per unit of length; this
    will not fully block light.

Second there is an emissive, glowing, component. This field is added directly to
the final image, washing out but not occluding geometry behind it. This is
useful for fire-style effects. It can also be useful for visualizing data
because it allows interior detail to shine through the outer layers.

@parameters

Visualization Mode:
    #id: vismode
    Volume primitives have a built-in visualization mode. If a __Density Field__
    is specified, it will be overridden with this visualization mode.

Minimum:
    #id: rangemin
    Values in the __Density Field__ will be remapped from the given __Minimum__
    and __Maximum__ values into the 0..1 range. This is the default range for
    all other volumes unless the override is specified.

Maximum:
    #id: rangemax
    Values in the __Density Field__ will be remapped from the given __Minimum__
    and __Maximum__ values into the 0..1 range. This is the default range for
    all other volumes unless the override is specified.
    
Density Scale:
    #id: densityscale
    Fixed multiplier on the density field to control how opaq
... (truncated, full doc is 11056 chars)
```

#### sop/attribfromvolume

```
= Attribute from Volume =

#type: node
#context: sop
#internal: attribfromvolume
#icon: SOP/attribfromvolume
#tags: attrs, volumes, merge
#since: 11.0
#verb_since: 16.5

"""Copies information from a volume onto the point attributes of
another piece of geometry, with optional remapping."""

@parameters

Group:
    The points in the first input that will have their attributes
    set from the volume values.

Volume:
    The volumes in the second input to use for sampling the
    attribute values.  If there are not enough volumes for the
    size of the attribute, the volumes will be re-used in turn.

    For convenience, volumes may be specified directly by "name",
    ie, the value of their name attribute.  Thus the density
    volume can be retrieved with "density" and the velocity set of
    three volumes with `vel.*`.

== Attribute ==

These parameters control what attribute the node saves the volume
information into. They also control what type of attribute the node
creates. If the attribute already exists in the first input, the
node ignores the creation parameters.

Attribute Name:
    Name of the attribute.

Create Variable Mapping:
    Specifies whether to create a local variable for the attribute.

Local Variable:
    The name scripts/expressions can use to refer to the attribute as
    a local variable. If you leave this blank, Houdini will use the
    name of the attribute in all caps.

Attribute Type:
    The sort of attribute to create.  
    The __Vector__ attribute is distinct from a triple of floats because it is often transformed like a normal.

Attribute Size:
    The number of components in the attribute type. For example,
    setting __Attribute type__ to "Float" and __Attribute size__ to
    `1` creates a simple scalar float attribute.
    
Default:
    The default value of the attribute. Four text fields are always
    visible but the node only uses the number of fields corresponding
    to the __Attribute size__. If the size is greater than `4`
... (truncated, full doc is 3132 chars)
```

### Key VDB SOP Nodes

#### sop/convertvdb

```
= Convert VDB =

#type: node
#context: sop
#internal: convertvdb
#icon: SOP/convertvdb
#tags: convert, tessellate, volumes
#since: 12.5
#verb_since: 16.5

"""Converts sparse volumes."""

This node converts sparse volumes, or VDBs, into other types.

It provides some extra options not available through the [Convert SOP|Node:sop/convert].

This also allows the conversion of volumes into VDBs.

For converting to polygons, the second and third inputs can be optionally
supplied. The second input provides a reference polygon surface for converting
the volume, which is useful for converting fractured VDBs back to polygons.
The third provides additional VDB fields which can be used for
masking (which voxels to convert to polygons), and/or for specifying an
adaptivity multiplier.

@parameters

Group:
    Subset of primitives to convert.
    
Convert To:
    What form of conversion to perform.

    Volume:
        The VDB is converted to a dense volume.  This allows legacy tools
        to understand the primitive.  VDBs with effective resolutions over
        1000^3 will have difficulties being efficiently represented.
    
    VDB:
        Convert into a VDB.

        If the input is a Volume Primitive, it is converted into
        a VDB.  The resulting VDB will be the same class as the input,
        so a fog volume becomes a fog VDB, and a SDF volume an SDF VDB.

    Polygons:
        The VDB is surfaced along the specified iso value.  Polygons
        are created.

    Polygon Soup:
        The VDB is surfaced, but a polygon soup is created.  While polygon
        soups do not support most editing operations, they are a more
        compact way of storing dense meshes.

Split Disjoint Volumes:
    When converting VDB to dense volumes, create multiple volume primitives per
    VDB for unconnected regions where possible. This allows very large and
    sparse VDBs to be converted with less memory usage.

VDB Class:
    If after converting the VDB, it is still a VDB, it is c
... (truncated, full doc is 7172 chars)
```

#### sop/vdbfrompolygons

```
#type: node
#context: sop
#internal: vdbfrompolygons
#icon: SOP/vdbfrompolygons
#since: 12.5
#verb_since: 16.5

#tags: create, model

= VDB from Polygons =

"""Converts polygonal surfaces and/or surface attributes into VDB volume primitives."""

:include volume_types:

NOTE:
    The input geometry must be a quad or triangle mesh.
    This node will "convex" the input surface into such a mesh if it isn't.

This node can create a distance field (signed (SDF) or unsigned) and/or a density (fog) field.

NOTE:
    If you create an __Unsigned Distance Field__, inside and outside will not be considered and the source geometry doesn't have to be airtight.

When you create a fog field you can choose to fill the band of voxels on the surface or (if you have an airtight surface) fill the surface (see the __Fill interior__ parameter).

Since VDB primitives only store the voxels around the surface, they can have a much a higher effective resolution than creating a traditional volume with [IsoOffset|Node:sop/isooffset].

You can connect a VDB to the second input to automatically use that VDB's orientation and voxel size (see the __Reference VDB__ parameter).

@parameters

Voxel Size:
    #id: voxelsize

    The size of voxels in the output VDB volume.
    Surface features smaller than this will not be in the output VDB.
    
Reference VDB:
    #id: group
    
    If the second input is connected, you can enter the name of a VDB primitive in the second input to copy the orientation and voxel size from it.
    
    See [specifying volumes|/model/volumes#group].

Distance VDB:
    Creates a signed distance field (SDF).
    An SDF stores the distance to the surface in each voxel.
    (If the voxel is inside, the distance is negative.)

Fog VDB:
    Creates a density field.
    Voxels in the band on the surface store `1` and voxels outside store `0`.
    The size of the filled band is controlled with the __Interior Band Voxels__.
    
    Turn on __Fill interior__ to create a solid VD
... (truncated, full doc is 4926 chars)
```

#### sop/vdbfromparticles

```
#type: node
#context: sop
#internal: vdbfromparticles
#icon: SOP/vdbfromparticles
#since: 12.5
#verb_since: 16.5

#tags: create, model

= VDB from Particles =

"""Converts point clouds and/or point attributes into VDB volume primitives."""

:include volume_types:

This node can create a distance field (signed (SDF) or unsigned) and/or a density (fog) field.

Since VDB primitives only store the voxels around each point, they can have a much a higher effective resolution than creating a standard Houdini volume.

NOTE:
    This node uses the point scale attribute (`pscale`) on the input points to convert them to spherical densities.
    This attribute is set by the [Attribute POP|Node:pop/attribute] or the [Point SOP|Node:sop/point].
    
    If points are smaller than 1.5 voxels, they cannot be resolved and will not appear in the VDB.
    
    You can also scale all sizes using the __Point radius scale__ parameter.

You can connect a VDB to the second input to automatically use that VDB's orientation and voxel size (see the __Reference VDB__ parameter).

@parameters

Voxel Size:
    The size of voxels in the generated VDB volume primitive.
    Points smaller than this cannot be resolved by the VDB so will not be in the output.

Reference VDB:
    #id: group
    
    If the second input is connected, you can enter the name of a VDB primitive in the second input to copy the orientation and voxel size from it.
    
    See [specifying volumes|/model/volumes#group].

<!-- :include vdbfrompolygons#group: -->

Distance VDB:
    Create a distance field VDB, where each voxel stores the distance to the nearest point.

Fog VDB:
    Creates a density field, where a voxel is `1` inside a point (that is, the sphere centered around the point with radius defined by the point's `pscale` attribute), and `0` outside.
    
Mask VDB:
    Create a mask field VDB.
    
    Generate an alpha mask that is very useful for subsequent constrained level
    set smoothing of the level set surface
... (truncated, full doc is 5245 chars)
```

#### sop/vdbcombine

```
#type: node
#context: sop
#internal: vdbcombine
#icon: COMMON/openvdb
#since: 12.5
#verb_since: 16.5

#tags: vdb, volumemix, vdbresample, vdbmerge

= VDB Combine =

"""Combines the values of two VDB volumes in various ways."""

:include volume_types:

The [Volume Mix SOP|Node:sop/volumemix] also works on VDBs.
However, Volume Mix only operates on the "active" area of the destination
volume.
That is, it will only update the "non-empty" voxels in the destination VDB.
To get a true union of two disjoint VDB volumes, you must use this node.

@parameters

See [specifying volumes|/model/volumes#group].

Group A:
    The volume primitives to be used from the first input.
    
Group B:
    The volume primitives to merge in from the second input.

Flatten All B into A:
    Requires that there is only one VDB in the A group.  Every VDB
    in the B group will, in turn, be combined with the VDB in
    the A group.  This can flatten a large collection of VDBs into
    a single VDB.

Combine A/B Pairs:
    If disabled, each VDB in the A group will be combined with
    the first VDB in the B group.  If enabled, the combination
    will be done pairwise.
    
Operation:
    Each voxel that is active in either of the input grids
    will be processed with this operation.

    Copy A:
        Use `A`, ignore `B`.
        
    Copy B:
        Use `B`, ignore `A`.
        
    Invert A:
        Use `0 - A`
        
    Add:
        Add the values of `A` and `B`.

	NOTE:
	    Using this for fog volumes (ie. density values between 0 and 1)
	will push density values over 1.0, which causes a bright interface
	between the input volumes when rendered. Try using the
	`A + (1 - A) * B` operation to avoid this.

    Subtract:
        Subtract the values of `B` from the values of `A`.
        
    Multiply:
        Multiply the values of `A` and `B`.
        
    Divide:
        Divide the values of `A` by `B`.
        
    Maximum:
        Use the maximum of each corresponding value from `A` a
... (truncated, full doc is 5211 chars)
```

#### sop/vdbresample

```
#type: node
#context: sop
#internal: vdbresample
#icon: COMMON/openvdb
#since: 12.5
#verb_since: 16.5

#tags: vdb, volumemix, vdbcombine

= VDB Resample =

"""Re-samples a VDB volume primitive into a new orientation and/or voxel size."""

:include volume_types:

NOTE:
    This node does not filter the results.
    If you change the resolution you may get aliasing artifacts.

@parameters

Group:
    The name(s) of the VDB volume primitives in the input to be re-sampled.
    See [specifying volumes|/model/volumes#group].

:include vdbfrompolygons#group:
    
Interpolation Order:
    How to interpolate positions.
    
    Nearest neighbor:
        Choose the value from the nearest voxel.
        This is fast but can cause aliasing artifacts.
    
    Tri-linear:
        Matches what [Volume Mix|Node:sop/volumemix] and [Vex:volumesample] do.
    
    Tri-quadratic:
        Smoother than tri-linear, but slower.

Define Transform:
    How to generate the new VDB's transform.

    Explicitly:
	Define an explicit transform to resample with.  Note that this
	is specified in index space, not SOP space, so the translation
	amounts will scale with voxel size.
            
    To Match Reference VDB:
        Use the transform and voxel size from a VDB in this node's second input.
        The result is a copy of the first input, aligned to the second input.
            
    Using Voxel Size Only:
        Set a new voxel size, increasing or decreasing the resolution.
        This can be applied to the transform of the input VDB or 
        as a new axis-aligned linear transform.
    
    Using Voxel Scale Only:
        Scale the voxel size, increasing or decreasing the resolution.
        This can be applied to the transform of the input VDB or 
        as a new axis-aligned linear transform.

Transform Order:
    The order of operations for the new transform.
    
Rotate Order:
    The order of rotations for the new transform.
    
Translate Voxels:
    The shift, in voxels, of t
... (truncated, full doc is 3774 chars)
```

#### sop/vdbsmooth

```
#type: node
#context: sop
#internal: vdbsmooth
#icon: COMMON/openvdb
#since: 12.5
#verb_since: 16.5

#tags: vdb, merge

= VDB Smooth =

"""Smooths out the values in a VDB volume primitive."""

:include volume_types:

For each voxel, this node computes an average (see the __Operation__ parameter) from the surrounding values and sets the voxel to that average.
(The "surrounding area" is a cube, despite the name __Filter Voxel Radius__).

NOTE:
    To smooth an SDF, use [VDB Smooth SDF|Node:sop/vdbsmoothsdf].

@parameters

Group:
    The name of VDB primitive(s) in the input to be smoothed.
    See [specifying volumes|/model/volumes#group].

Alpha Mask:
    #id: maskname
    If enabled, it will use the second input's VDB for alpha masking. Assumes
    voxel values are between 0 to 1 inclusive.
    See [specifying volumes|/model/volumes#group] for more information.

Operation:
    How to smooth the voxel values.

    Mean Value:
        Find the mean (`total/count`) of the surrounding values.
        This is equivalent to a box blur of the same radius.
    
    Median Value:
        Find the median (middle value) of the surrounding values.
        This is useful for de-spiking noisy data as extreme values will not contribute to the final result.

Filter Voxel Radius:
    #id: radius
    
    The number of voxels to run the smooth operation over.
    This is measured in voxels, not distance.
    This distance defines a _cube_, so increasing the "radius" will exponentially increase the work.

Iterations:
    Number of times to repeat the smoothing operation.

    For a cone blur, multiply the radius by `0.454545` and use two passes.
    For a gaussian, multiply the radius by `0.33` and use four passes.

:include vdbrenormalizesdf#accuracy:

Invert Alpha Mask:
    #id: invert
    Inverts the alpha mask so that values from 0-1 maps to 1-0.
    
Min Mask Cutoff:
    #id: minmask
    Alpha mask values below this are mapped to 0.

Max Mask Cutoff:
    #id: maxmask
    Alpha ma
... (truncated, full doc is 2076 chars)
```

#### sop/vdbanalysis

```
#type: node
#context: sop
#internal: vdbanalysis
#icon: COMMON/openvdb
#since: 12.5
#verb_since: 16.5

#tags: vdbs

= VDB Analysis =

"""Computes an analytic property of a VDB volumes, such as gradient or curvature."""

:include volume_types:

This node computes some property from the values of VDB volumes, and generates new VDB volumes where the voxel values are the computed results.
Using the __Output name__ parameter you can choose whether the results volumes replace the original volumes.

@parameters

Group:
    The name(s) of the VDB primitives to analyze.
    See [specifying volumes|/model/volumes#group].

Operator:
    What to compute. The labels on the items in the menu indicate what datatype the incoming VDB volume must be and the datatype of the output volume.

    Gradient (scalar -> vector):
        The gradient of a scalar field.
        
    Curvature (scalar -> scalar):
        Mean curvature of a scalar field.
        
    Laplacian (scalar -> scalar):
        The Laplacian of a scalar field.
        
    Closest Point (scalar -> vector):
        Generates voxels containing the location of the closest point on a surface defined by the incoming signed distance field.
        
        You can then use the resulting field with the [VDB advect points node|Node:sop/vdbadvectpoints] to stick points to the surface.
        
    Divergence (vector -> scalar):
        The divergence of a vector field.
        
    Curl (vector -> vector):
        The curl of a vector field.
        
    Magnitude (vector -> scalar):
        The length of the vectors in a vector field.
        
    Normalize (vector -> vector):
        Divides vector field's values by their lengths.

Mask VDB:
    VDB (from the second input) used to define the iteration space.

Output Name:
    How to name the generated VDB volumes. If you choose "Keep incoming names", the generated fields will replace the input fields.

Custom Name:
    If this is not blank, the output VDB will use this name.
... (truncated, full doc is 2069 chars)
```

#### sop/vdbactivate

```
#type: node
#context: sop
#internal: vdbactivate
#icon: COMMON/openvdb
#since: 12.5
#verb_since: 16.5

#tags: vdb, volumemix, vdbcombine, vdbvisualize

= VDB Activate =

"""Activates voxel regions of a VDB for further processing."""

:include volume_types:

Many volume operations, such as Volume Mix and Volume VOP, only process
active voxels in the sparse volume.  This can be a problem if you know a
certain area in space will evaluate to a non-zero value, but it is
inactive in your original volume.

The VDB Activate SOP provides tools for manipulating this active region.
It can also fill the newly added regions to a constant value, useful
for interactively determining what is changing.

TIP: To see the current active region, you can use the VDB Visualize SOP
     and set it to Tree Nodes, Disabled; Active Constant Tiles, Wireframe Box; 
     and Active Voxels, Wireframe Box.

@parameters

See [specifying volumes|/model/volumes#group].

Source Group:
    The vdb primitives to change the active region in.
    
Operation:
    The vdb's current region is combined with the specified region
    in one of several ways.

	Union:
	    All voxels that lie in the specified region will
	    be activated.  Other voxels will retain their original
	    activation states.
	
	Intersect:
	    Any voxel not in the specified region will be deactivated
	    and set to the background value.
	
	A - B:
	    Any voxel that is in the specified region will be deactivated
	    and set to the background value.
	
	Copy:
	    If a voxel is outside the specified region, it is set
	    to inactive and the background value.  If it is inside,
	    it is marked as active.

Value:
    In the Union and Copy modes, when voxels are marked active they can also be
    initialized to a constant value.  This will be done to all voxels that are
    made active by the specification - including those that were already
    active.

    Thus, the Voxel Coordinates option will have the effect of setting a cube
    
... (truncated, full doc is 5269 chars)
```

#### sop/vdbvisualizetree

```
#type: node
#context: sop
#internal: vdbvisualizetree
#icon: COMMON/openvdb
#since: 12.5
#verb_since: 16.5

#tags: vdbs

= VDB Visualize Tree =

"""Replaces a VDB volume with geometry that visualizes its structure."""

:include volume_types:

This node may be useful to experts for checking if the VDB volume is wasting memory.

@parameters

Group:
    The name(s) of VDB primitives in the input to visualize.
    See [specifying volumes|/model/volumes#group].

Color:
    Specify whether to draw in color (which adds the `Cd` attribute).

Frustrum:
    For VDB primitives created based on a frustum, draw the corresponding frustum bounding box.
    See the __Frustum__ and __From camera__ modes of the [VDB node|Node:sop/vdb].

Leaf Nodes:
    When enabled, it will draw leaf nodes with the specified method.
    If __Color__ is enabled, they are drawn in blue.

    Wireframe Boxes:
	    Draw as wireframe boxes.
    Solid Boxes:
        Draw as solid boxes.

Internal Nodes:
    When enabled, it will draw non-leaf nodes with the specified method.
    If `Color` is enabled, the first internal node level is shown in green,
    otherwise shown in orange.

    Wireframe Boxes:
	Draw as wireframe boxes.
    Solid Boxes:
        Draw as solid boxes.

Active Tiles:
    When enabled, draw nodes that are active but hold the default (empty) value in the specified method.
    Positive values are red, negative values are white.

    Points:
        Draw a single point in the middle of each node.
    Wireframe Boxes:
	    Draw as wireframe boxes.
    Solid Boxes:
        Draw as solid boxes.

Active Voxels:
    When enabled, draw active voxels in the specified method.
    They are colored red if positive valued, white if negative valued.
            
    Points:
        Draw a single point in the middle of each voxel.
    Wireframe Boxes:
	    Draw as wireframe boxes.
    Solid Boxes:
        Draw as solid boxes.

Ignore Staggered Vectors:
    Draw staggered vectors as if they were collocat
... (truncated, full doc is 2495 chars)
```

### Volume LOP Node

#### lop/volume

```
#type:     node
#context:  lop
#internal: volume
#icon:     LOP/volume
#since: 18.0

= Volume =

"""References volume data on disk into a volume prim containing field prims."""

This node reads volume files from disk and creates volume and field primitives pointing to the contained data.


@parameters

~~~ Frame Range/Subframes ~~~

:include _sampling#sampling_block/:

:include _sampling#subframe_sampling_block/:

~~~

Primitive Path:
    #id: primpath

    Create the main volume primitive at this scene graph path.

Primitive Kind:
    #id: primkind

    Set this as the new volume prim's [kind|/solaris/glossary#kind]. The default is None.

Parent Primitive Type:
    #id: parentprimtype

    If any parents of the path in __Primitive Path__ do not exist, this node will automatically create them. In this case, it will create parent nodes of this type.

Primitive Specifier:
    #id: specifier

    Determines the USD [specifier|/solaris/glossary#specifiers] set on the volume primitive and any ancestor primitives created by this LOP.

Generate Errors For Missing Files:
    #id: errorformissingfiles

    If any volume files cannot be found or cannot be loaded, this node will generate an error, causing all downstream nodes to also error. Turn off this option to generate warnings instead. This is only recommended in the early stages of a project where the integrity of the output does not need to be validated.

~~~

Files:
    This node can reference multiple files as fields of a single volume. Set this to the number of fields to read, or click the plus and minus buttons to add or remove field file references.

File Path:
    #id: filepath

    The location of the volume file on disk. USD is not capable of representing volumes currently. It can only point to volumes stored as separate files on disk. These files can be `BGEO` _or_ `VDB` when working _within_ Houdini and using a Houdini render delegate. If you want to use the volume data with non-Houdini processes, then you'll 
... (truncated, full doc is 2560 chars)
```

