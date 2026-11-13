# Houdini Node Reference (from official offline manual)
Auto-extracted from HFS/houdini/help/nodes.zip - raw SideFX documentation.
Use `query_help` bridge command for any node not listed here.

---

## lop/layout

```
= Layout =
#type: node
#context: lop
#internal: layout
#icon: LOP/layout
#group: usdassets   
#since: 19.0

"""Provides tools for populating a scene with instanced USD assets. You can place individual components, paint/scatter components in different ways using customizable brushes, and edit existing instances."""


== Overview ==

The layout node provides a user interface and viewer state for placing/scattering/painting USD assets as point instances.

This node creates a USD point instancer in the scene tree. When you place, paint, scatter, delete (and so on) assets, the node is actually working with points, and instancing USD assets onto them.

:video:
    #src: /videos/layout_place.mp4

Interactions in the viewer are implemented by interchangable _brushes_. A brush is essentially a SOP network HDA that processes instancing points and user interactions, and you can [create your own custom brushes|/solaris/support/layout_brush].

The Layout node also lets you switch to [edit mode|#edit_mode], which provides the same tools as the [Edit LOP|Node:lop/edit], for positioning assets using handles and/or physics simulations.

The layout has a custom UI in the parameter that is divided into distinct vertical areas:

[Image:/images/nodes/lop/layout_ui_anno.jpg]

* The __Instancer Path__ parameter controls where in the scene graph tree the node creates the USD point instancer prim it uses to instance assets onto points.

* You can press ((Shift + B)) in the viewer to switch between [brush mode|#brush_mode] and [edit mode|#edit_mode]. In the parameters, the settings for the two modes are on separate tabs.

* At the top of the __Brush__ tab, the node shows all the available [layout brushes|#brush_mode].

* Below the brush gallery, the node shows the parameters of the currently selected brush.

* Below the brush parameters is the [working set|#working_set] area, with its own toolbar.


== Asset catalog == (asset_gallery)

Before you can start placing and scattering assets, you must set up your _working set_, and before you can add assets to the working set, you must set up an _asset catalog_.

:task: Show the [asset catalog interface|/ref/panes/assetgallery]:

    * In the Layout node UI, click [Icon:BUTTONS/addasset] in the toolbar above the working set (the dark area at the bottom of the interface).

        This opens the asset catalog pane in a floating window.

    * [Add an Asset Catalog pane tab to the desktop layout|/basics/panes]: click the plus button to the
... (truncated, full doc is 12501 chars)
```

---

## lop/instancer

```
= Instancer =
#type:     node
#context:  lop
#internal: instancer
#icon:     SOP/copytopoints
#since: 17.0

"""Instances or copies primitives onto points."""


== Overview ==

USD supports two types of instancing: _instanceable primitives_ (where multiple copies of the same branch are aliases to shared storage) and _point instancing_ (where USD stores _points_ and _prototypes_ to copy onto the points, but only draws the copies at render time). See [USD instancing|/solaris/glossary#instancing] for more information.

This node can do both types of instancing: it can create a point instancer, or it can place instanceable prims based on the locations of points. (It can also reference in _real separate copies_ instead of instanceable prims.)

The thing or things you want to create multiples of are called the _prototypes_. This node assumes the prototypes already exist, connected to the first or second input.

The points you want to instance/copy onto are called the _targets_. The targets can be points or prim positions in the input scene graph tree, or you can generate them in the SOP subnet inside this node, or in a SOP node elsewhere in the node hierarchy.


== Example ==

:fig: [Image:/images/nodes/lop/point_instancer_lop.jpg]

    # In the network editor, use the ((Tab)) menu to create a torus.

        The "Torus" tool actually creates a [SOP Create LOP|node:lop/sopcreare]| that imports the result of a [Torus SOP|Node:sop/torus] into USD.

        On the SOP Create node, set the __Import Path Prefix__ to `/Geometry/torus`.

    # Add a [Sphere LOP|Node:lop/sphere]. Set the __Primitive Path__ to `/Geometry/ball` and the __Uniform Scale__ to `0.05`.

    # Add a [Cone LOP|Node:lop/cone]. Set the __Primitive Path__ to `/Geometry/cone` and the __Uniform Scale__ to `0.05`.

    # Add a [Cylinder LOP|Node:lop/sphere]. Set the __Primitive Path__ to `/Geometry/tube` and the __Uniform Scale__ to `0.05`.

    # Add an Instancer LOP.

        * Set the __Primitive Path__ to `/Geometry/shapes`.

        * Set the __Method__ to __Point Instancer__.

        * Set the __Location Source__ to __First Input's Points__.

        * Set the __Location Primitives__ to `/Geometry/torus/mesh_0`.

        * Set the __Prototype Source__ to __First Input__.

        * Set the __Prototype Primitives__ to `/Geometry/ball /Geometry/cone /Geometry/tube`.

        * Set the __Prototype Index__ to __Random__.

        The node randomly instances a ball, cone, or tube at each point of the
... (truncated, full doc is 17859 chars)
```

---

## lop/reference

```
= Reference =
#type: node
#context: lop
#internal: reference
#version: 2.0
#icon: LOP/reference
#group: layers
#since: 19.5

"""References the contents of a external USD files and/or layers created by other LOP nodes into a branch of the existing scene graph tree. Can also remove or replace existing references."""

== Overview ==

This node lets you reference a tree of primitives from a different location, into your current scene graph. These other locations can be external files, other LOP nodes, or even different primitives within the same tree. Multiple references can be made to the same source, allowing you to re-use existing primitives.

See the section [References Explained|#refdetails] for details about this USD concept.

== Tips == (tips)

* When an __Action__ parameter is set to __Create New Primitives__, the __Primitive Path__ must specify a single primitive path. This parameter is re-evaluated for each reference being created, and if necessary will be made unique by appending a numeric suffix.

* When an __Action__ parameter is set to __Edit Existing Primitives__, the __Primitive Path__ is interpreted as a primitive pattern. The reference is added to every primitive that matches the pattern.

* If the prim you specify to reference onto already has existing references, the new reference will be composed _with any existing references_. See the __Composition > Pre-Operation__ parameter for how to clear existing references before adding a new one.

* The reference operations specified on this node are performed in order, so multiple references can be added to a single primitive. For example, a `Create` action for the multi-input might create a some new primitives, then a subsequent `Inherit` operation can add an inherit arc to each of these newly created reference primitives.

== How to ==

The "target" that gets referenced onto a primitive in the scene graph tree is often in an external file, however this node can also reference a prim in the output of another LOP node.

:task: Reference a prim in an external file:

    # Set the __Primitive Path__ to the scene graph path at which the referenced prim should be attached.

    # Set the __Reference Type__ to __Reference Files__ or __Payload Files__ (see [payloads|/solaris/glossary#payloads] for more information).

    # Set the __File Pattern__ to the file path of the USD file to reference in. This file path can include wild cards to match multiple files on disk, in which case a new primitive will be
... (truncated, full doc is 19333 chars)
```

---

## lop/merge

```
= Merge =
#type: node
#context: lop
#internal: merge
#icon: COMMON/merge
#group: util
#since: 18.0

"""Merges the layers from incoming stages into a unified layer stack."""


== Overview ==

This node takes multiple inputs (each of which represents a "stack" of one or more USD layers) and merges them into a stage containing one layer stack in the output. This is useful when you want to combine separate pieces of a scene graph, each authored by a different chain of LOP nodes, into a unified whole.

* The order of inputs matters. Layers in earlier inputs are _weaker_ than layers in later inputs when combined in the output.

* This node has different styles for combining layers from the inputs. See the __Merge style__ parameter. Some styles flatten the contents of input layers into one or more output layers.

[Image:/images/nodes/merge_lop_styles.svg]


== Tips ==

* This node is like [sublayering|/solaris/glossary#sublayers] but for in-memory trees. Similarly, the [Graft Stages LOP|Node:lop/graftstages] is like [referencing|/solaris/glossary#sublayers] but for in-memory trees. It combines scene graph trees by choosing the locations at which each input stage's tree is attached on the output tree.

* Merge styles that simply merge layers are fast. Styles that flatten layers are more expensive. You may want them to generate a particular arrangement of layers when [saving the stage to disk with USD render node|Node:out/usd], but often the same effect can be accomplished in the USD ROP itself by flattening implicit layers. This way the flattening cost is only paid when writing the USD files to disk, not when working in the LOP network.

* If an input has a [Layer Break LOP|Node:lop/layerbreak] further up the chain, the sublayers from above the Layer Break can be discarded for any merge style. This should be done when the Merge LOP has multiple inputs with a common "root" higher up the network (a "diamond" shaped set of connections). In this situation it is a good idea to put a Layer Break at the branch points for all but the first merge connection. And __Strip Layers Above Layer Breaks__ should be enabled.

* This LOP will often be much slower to cook the first time, and much faster on subsequent cooks. Factors that may trigger another slow cook include rewiring input connections, changing the __Merge Style__ or __Strip Layers__ parameters on this node, or adding new scene graph primitives to some inputs, especially if the primitives being added or removed overla
... (truncated, full doc is 7836 chars)
```

---

## lop/sopcreate

```
= SOP Create =
#type: node
#context: lop
#internal: sopcreate
#icon: LOP/sopcreate
#group: geometry
#since: 18.0

"""Lets you create geometry in a SOP subnetwork inside this node, so you can create geometry in-place in the LOP network instead of needing a separate SOP network."""


== Overview ==

This node is essentially an embedded SOP subnetwork combined with a [SOP Import LOP|Node:lop/sopimport]. It lets you create SOP geometry "in place" in the subnet, and then "import" it from the subnet, with the same SOP-to-USD controls as on the SOP Import node.

See [how SOP import works|/solaris/sop_import] for detailed information on how the importer converts SOP information into USD.


== How to ==

# Add a SOP Create node.

# In the network editor, double-click the SOP Create node to go inside to the SOP subnet.

# Use SOPs to generate geometry.

    As you develop the geometry, you can add `path` string attributes to SOP primitives to specify where they should appear in the USD scene graph tree when imported. If you specify a relative path (doesn't start with `/`), the value is appended to the SOP Create node's __Import Path Prefix__ parameter.

    Remember that for polygons, all faces you want to be part of the same USD mesh prim must have the same value in their `path` attribute.

    See [generating geometry hierarchy|/solaris/sop_import].

    (The SOP Create node can also create USD _geometry subsets_ based on SOP string attributes and/or groups. Geometry subsets are useful for assigning materials to groups of faces.)

# End the geometry network with an [Output SOP|Node:sop/output].

    The Output node is used as the output for the subnetwork. If you don't have an Output node in the subnet, it uses whatever node has the display flag.

# In the network editor, press ((U)) to go back up to the LOP network.

# In the SOP Create node's parameters, set the __Import Path Prefix__.

    Any geometry that doesn't have a `path` attribute is given a generated name (for example, all polygons go into a mesh prim named something like `mesh_0`), and put under this prim path.

    Any geometry with a relative `path` attribute value is prefixed with this prim path.

    See [generating geometry hierarchy|/solaris/sop_import].


@parameters

:include sopimport#asreference:

:include sopimport#copycontents:

:include sopimport#adjustxformsforinput:

:include sopimport#bindmaterials:

:include sopimport#reftype:

:include sopimport#refprim:

:include sopimport#refprimpa
... (truncated, full doc is 4184 chars)
```

---

## lop/sopimport

```
= SOP Import =
#type: node
#context: lop
#internal: sopimport
#icon: LOP/sopimport
#group: geometry
#since: 17.0

"""Imports geometry from a SOP network into the USD scene graph."""


== Overview ==

The imported geometry is translated to a native USD representation which may consist of many different native USD primitive types (you can control the hierarchical structure of the imported USD using attributes on the source SOP geometry).

See [how SOP import works|/solaris/sop_import] for detailed information on how the importer converts SOP information into USD.

You can import SOP geometry by sublayering (composing it over the current contents of the scene tree) or referencing (attaching it at a certain branch of the scene tree). (See [sublayering and referencing|/solaris/glossary#sublayers].)

The layer containing the imported geometry has source metadata in format that tells Houdini's USD plugins to get the geometry from a SOP node instead of a file on disk.

This node can put the imported geometry in the _active layer_, so it can be modified by LOP nodes connected to this node's output.

In addition to the geometry itself, you can import Houdini attributes on the geometry as USD primvars.

NOTE:
    This node works by converting SOP geometry into a hierarchy of USD geometry prims, and then importing that USD data into the scene graph tree (by [sublayering or referencing|/solaris/glossary#sublayers]).

    Knowing this will help you interpret some of the parameters, such as "which prim to reference in". They are speaking in terms of how to deal with the already-converted USD geometry prims.


== How to ==

:task:Separate polygon meshes by connectivity:
    # In the SOP network, add a [Connectivity SOP|Node:sop/connectivity].

        * Set the __Connectivity Type__ to __Primitive__.
        * Set the __Attribute__ to `piece`.

        This creates a `piece` integer attribute on the polygons, where each polygon in a connected island has the same `piece` attribute value as all other polygons in the island.

        Unfortunately, SOP Import can't use an integer attribute to generate paths. We'll need to use this attribute to generate a string attribute.

    # After the Connectivity node, add an [Attribute Create SOP|Node:sop/attribcreate].

        * Set the __Name__ to `path`.
        * Set the __Class__ to __Primitive__.
        * Set the __Type__ to __String__.
        * Set the __String__ value to a name or prim path you want to use for the connected 
... (truncated, full doc is 13947 chars)
```

---

## lop/configurelayer

```
= Configure Layer =
#type: node
#context: lop
#internal: configurelayer
#icon: LOP/configurelayer
#group: layers
#since: 18.0

"""Edits metadata on a layer."""


== Overview ==

This node edits metadata that affects how a USD layer functions.

* Some of the metadata is stored on the layer root prim and is saved with the layer on disk.

* Some metadata is stored in the `/HoudiniLayerInfo` prim and controls _how_ the layer is written to disk. This primitive is not saved to any USD output.


== Tips ==

* This node will only author a bit of metadata if the corresponding parameter has its checkbox turned on. If the checkbox for a parameter is off, the node will not change any existing metadata corresponding to that parameter.


@parameters

Save Path:
	Where the file will be saved if and when the USD is written to disk (by a [USD Render ROP|Node:out/usd]). (This is stored in `/HoudiniLayerInfo` and is not saved to any USD output.)

	This path can be altered by an [output processor|/solaris/output#processors] if you have them configured on the render node. For example, it is common in Houdini to have file paths relative to `$HIP`, but in USD they should be relative to the root layer file. By default, an output processor on the USD Render ROP does this transformation automatically.

Default Primitive:
	Sets the [default primitive|/solaris/glossary#default_prim] for this layer. If another USD file references this layer, but does not explicitly name a primitive, it is given the _default primitive_. This sets the default primitive for this layer. It must be a root prim (`/prim_name`) and it must exist in this layer.

Comment:
	Sets a comment on this layer. This comment has no meaning to USD, but may be used to describe the purpose of the layer, or any other information you may wish to associate with the layer.

Start Time:
	Sets the start time of the playable range for this layer. (This is not enforced in any way, and the layer may not have any animation. This may be used by [Houdini's viewer|/solaris/view] and tools such as `usdview`.)

End Time:
	Sets the end time of the playable range for this layer. (This is not enforced in any way, and the layer may not have any animation. This may be used by [Houdini's viewer|/solaris/view] and tools such as `usdview`.)

Time Codes per Second:
	Applies a scaling factor to time samples stored in the layer. You can use this to non-destructively speed up or slow down animation in the layer.

Frames per Second:
	For data specifie
... (truncated, full doc is 6134 chars)
```

---

## lop/graftbranches

```
= Graft Branches =
#type: node
#context: lop
#internal: graftbranches
#icon: LOP/graftbranches
#group: util
#since: 18.5

"""Takes prims/branches from the second input and attaches them onto branches of the scene graph tree in the first input."""


== Overview ==

Unlike [referencing in a file|/solaris/glossary#sublayers] with the [Reference LOP|Node:lop/reference], this node is more for performing "surgery" on anonymous in-memory layers to build them into a tree you want to write out. It flattens the prims from the other inputs and directly attaches them in-memory to the tree in the first input, rather than creating a composition arc.

This node is very similar to the [Graft Stages LOP|Node:lop/graftstages] node, however instead of attaching the entire contents of a stage from another input, it attaches individual primitives (and any descendants).

This node has a multi-parm to allow you to graft multiple primitives from the second input onto the "main" scene graph tree in the first input.

This can be very useful to grab objects from an imported stage, or changes from an edited stage, and put them in different locations in the current stage.


== Where to attach the imported prims == (attach)

By default, all destination paths are added *under* the scene graph path you set in __Primitive Path__ (this is, this path is prefixed to the destination paths you set for each prim in the multi-parm).

The default is the path of the _last modified prim_ in the first input, which is not very useful. *You should change this* to be the parent prim under which you want to attach the grafted branches.

For each "source prim" you specify in the multi-parm, you can specify a __Destination Prim Path__. This is added to the path in __Primitive Path__.

So, if you are putting all grafted prims in the place, or all under a common ancestor, it can be useful to set __Primitive Path__ to the common prefix of all the destination paths, and only specify the suffixes in the __Destination Prim Path__ for each graft. Or, for full control in the multi-parm, you can set this to `/` and specify full destination paths in the multi-parm.

If you disable __Treat Destination Paths as Parents__, then prims will not be copied *under* the destination paths described above but, rather, directly into those paths. For example, if your source path is `/geo/sphere` and your destination path is `/new/ball`, you will either end up with `/new/ball/sphere` or `/new/ball` depending on the state of the 
... (truncated, full doc is 6044 chars)
```

---

## lop/xform

```
= Transform =
#type: node
#context: lop
#internal: xform
#icon: SOP/xform
#since: 17.0

"""Edits the transforms of selected USD primitives."""


== Tips ==

* This node adds an `xformOp:transform` attribute (part of the `UsdGeomXformable` schema) to the selected prim(s). This is more lightweight than parenting the prim to an `Xform` prim (see the [Xform LOP|Node:lop/createxform]).


@parameters

~~~ Frame Range/Subframes ~~~

:include _sampling#sampling_block/:

:include _sampling#subframe_sampling_block/:

~~~

:include _primpattern:

Transform Description:
    #id: xformdescription
    
    Because all USD edits are non-destructive, editing transforms is accomplished adding a `xformOp:transform` attribute. Each attribute name has a descriptive suffix. For example, if you set this to `foo`, it authors an attribute named `xformOp:transform:foo`. The resulting full attribute name must be unique among attributes on the same prim (Houdini will automatically alter the name by adding a number if it's not unique).

    The default (`$OS`) uses the node name as the descriptive suffix.

Apply Transform in World Space:
    (Default on) Apply the given transform as if it was in world space. When this is off, the transform is local. Technically, transform operations are always local, but this can be confusing (for example, a parent prim may have a rotation around Z, which will make a local move along X axis actually move the primitive along world Y). So this option exists to let you specify the transform more intuitively in world space, and have the node create a local transform that achieves the same effect.

Set Absolute Transform:
    When __Apply Transform in World Space__ is off and this is on, make this transform _the only active_ `xformOp:transform` attribute on the prim. This works by setting the `xformOpOrder` list to only contain the new transform attribute. (So any previously existing transform attributes are still on the prim, but aren't used because they're not listed in `xformOpOrder`.) 

:include _simple_prims#xOrd:

:include _simple_prims#t:

:include _simple_prims#r:

:include _simple_prims#s:

:include _simple_prims#shear:

:include _simple_prims#scale:

~~~ Pivot Transform ~~~

:include _simple_prims#xform_pivot_block/:
```

---

## lop/edit

```
= Edit =
#type:     node
#context:  lop
#internal: edit
#icon:     LOP/edit
#since: 17.0

"""Interactively transforms prims in the viewer. Can use physics collisions to position props realistically."""


== Overview ==

This tool is similar to the transform tools for Objects. You can select 


== How to ==

:task: Start editing in the viewport:

    # Click the [Icon:TOOLS/select] __Select__ tool (to the left of the view).

    # In the viewer, select the prims you want to edit.

    # Click the [Icon:TOOLS/move] __Move__, [Icon:TOOLS/scale] __Scale__, or [Icon:TOOLS/rotate] __Rotate__ tools (to the left of the view).

        This creates an Edit node in the network to store the changes you make to the selected prims.

:task: Start editing from the network editor:

    # Add or select an Edit node in the network.

    # In the viewport, press ((Enter)) to enter the node's __Edit__ state. You can now see a HUD in the viewport's upper left corner.

    # See "Change the selection" below for how to select the prims to edit.

:task: Change the selection:

    In the viewport, hold ((S)) to temporarily enter the __Select__ tool. With the key down, click or drag to select prims, then release the ((S)) key.

:task: See the node's parameter set:

    On the Parameter Editor, click the [Smallicon:PANETYPES/parameters] __Show/Hide Parameters__ button to switch from tabular view to parameter view.


== Using physics ==

:video:
    #src: /videos/physics_edit.mp4

* In the __Edit__ state, turn on __Use Physics__ in the operation toolbar (above the view).

* Select the prims you want to be able to move.

    * Selected prims can have their positions and rotations affected by the simulation. Unselected prims act as static colliders that don't move.

* You can use the handles to transform the selected prims all at once.

* Alternatively, you can drag on a selected prim to "push/pull" that prim by that point. Other selected prims can be affected by the prim you're dragging. Unselected prims act as static colliders that don't move.

* Shift-drag on a selected prim to "push/pull" all selected prims at once.

* Use the mouse wheel to drop or raise the selected prims with physics. This is useful to the objects into a natural-looking pile.


== Tips and notes ==

* By default the simulation uses the full prim geometry. For very detailed geometry, this can be slow and inefficient. See the [Simulation Proxy LOP|Node:lop/simulationproxy] for how to generate low-res collision geo
... (truncated, full doc is 4131 chars)
```

---

## lop/primitive

```
= Primitive =
#type: node
#context: lop
#internal: primitive
#icon: LOP/primitive
#group: prims
#since: 18.0

"""Bulk-creates one or more attributes of a certain type."""

Unlike the nodes for creating specific primitive types ([Cube LOP|Node:lop/cube], [Camera LOP|Node:lop/camera], and so on), this node doesn't provide parameters for setting attributes on the new primitives. Only the most basic properties common to all primitive types are available.

This node is primarily useful for setting up a quick scene graph hierarchy (say, a hierarchy of `Xform` prims) using a single node.

You can type primitive paths directly into the __Primitive Paths__ parameter. You can also use expressions (inside back-ticks) in __Primitive Paths__ to reference external data sources to generate the list of primitives that define the hierarchy.


@parameters

Primitive Paths:
    A list of scene graph paths where the new primitives should be created. Paths must be separated by white space. This parameter is a multi-line field to make it easier to edit and view an entire hierarchy of paths.

:include _simple_prims#primkind:

:include _simple_prims#parentprimtype:

Primitive Type:
    #id: primtype

    Set all created prims to have this type. The menu lists all concrete primitive types registered with the USD type system.

:include _simple_prims#specifier:


@related

::[Camera|Node:lop/camera]
::[Capsule|Node:lop/capsule]
::[Cone|Node:lop/cone]
::[Cube|Node:lop/cube]
::[Cylinder|Node:lop/cylinder]
::[Dome Light|Node:lop/domelight]
::[Light|Node:lop/light]
::[Render Product|Node:lop/renderproduct]
::[Render Settings|Node:lop/rendersettings]
::[Render Var|Node:lop/rendervar]
::[Scope|Node:lop/scope]
::[Sphere|Node:lop/sphere]
::[Xform|Node:lop/xform]
```

---

## lop/materiallibrary

```
= Material Library =
#type: node
#context: lop
#internal: materiallibrary
#icon: LOP/materiallibrary
#since: 17.0

"""Authors USD material primitives from shader VOP nodes."""


== Overview ==

NOTE:
    In Houdini 20, the Material Library LOP's way of creating materials changed fundamentally. In previous versions you could access all shader nodes from the library's root level. This often lead to confusion, because it was possible to mix incompatible shader nodes. Now, shaders are created inside subnets:

    * Karma Material Builder
    * USD MaterialX Builder
    * VEX Material Builder
    * USD Preview Material Builder

    The new approach also filters the nodes in the tab menu and it's, for example, not possible to add MaterialX nodes to a VEX subnet.

This node translates shader VOP nodes into USD material primitives. 

A newly created Material Library node uses a pattern asterisk `*` in the __Material VOP__ parameter to match children VOP nodes inside the LOP and translate them into USD materials. See [USD materials|#usdmat] below.

Alternatively, this LOP can also import Houdini VOP materials from other VOP networks (such as `/mat`), using __Auto-fill Materials__ button.

== Tips ==

* You can use patterns in the __Material VOP__ parameter.

* You can define a common USD path for all materials, using __Material Path Prefix__ parameter. Any material whose __Material Path__ multi-parm instance is not an absolute path will use it as a prefix.

* The __Material Path Prefix__ parameter can be used to specify either the ancestor primitive (if the path ends with a slash), or the ancestor path and the shader primitive name prefix (if the path does not end with a slash).

* If you want to re-do importing all materials (for example, to grab new materials), click __Clear__ in the multi-parm, then click __Auto-fill Materials__ again.

* Even though this node allows you to assign the material at the same time you import it, we recommend you use a separate node ([Material Linker LOP|Node:lop/materiallinker] or [Assign Material LOP|Node:lop/assignmaterial]) to assign materials. Keeping the two operations separate makes your network easier to understand for others.

* [Parameter VOPs|Node:vop/parameter] set to __Subnet Connector__ can be used within a Material Builder subnet, to promote a public interface. These inputs are editable using an [Edit Material Properties LOP|Node:lop/editmaterialproperties].

* Additionally, you can make the USD material interface more
... (truncated, full doc is 8889 chars)
```

---

## lop/assignmaterial

```
= Assign Material =
#type: node
#context: lop
#internal: assignmaterial
#icon: LOP/assignmaterial
#group: materials
#since: 18.0

"""Assigns a material to one or more USD primitives. You can use also programmatically assign materials using VEX, programmatically override material settings for each assignment, and programmatically assign materials to geometry subsets."""


== How to == (howto)

:task: Assign a material to one or more primitives:

    # In the __Primitives__ parameter, specify the primitive(s) you want to assign the material to. You can click the select button beside the text box to choose the primitives from the scene graph tree.

        You can also use [primitive patterns|/solaris/pattern] for advanced matching.
        This includes selecting all primitives in a collection, for example all prims in the `donuts` collection on `/table` using `/table.collections:donuts`

        TIP:
            If you assign a material to all prims in a collection, you probably also want to set the __Method__ (under __Material Binding__) to __Collection Based__, so the node assigns the material to the collection itself, rather than individually to each prim currently in the collection.

    # Set __Specify Material Using__ to __Explicit Path__.

    # Set __Material Path__ to the path of the USD material you want to assign. You can click the select button beside the text box to choose the material from the scene graph tree.

:task: Assign computed materials using VEX (advanced):
    
    # In the __Primitives__ parameter, specify the primitive(s) you want to assign the material to. You can click the select button beside the text box to choose the primitives from the scene graph tree. You can also use [primitive patterns|/solaris/pattern] for advanced matching.

    # Set __Specify Material Using__ to __VEXpression__.

    # In the __VEXpression__ box, enter a [VEX snippet|/vex/snippets] to compute the material to assign to each primitive.

        The snippet is run once for each selected primitive. The path of the current primitive is available as `@primpath`. The index of the current primitive is available as `@elemnum`, the total number of selected primitives is available as `@numelem`.

        Under __CVEX Bindings__, when __Autobind by Name__ is on (the default), each attribute on the current primitive is available as a VEX variable of the same name. This allows you to assign different materials based on a primitive's attribute values. (If you don't 
... (truncated, full doc is 16738 chars)
```

---

## lop/karmarendersettings

```
#type: node
#context: lop
#internal: karmarendersettings
#icon: LOP/karmarendersettings
#since: 18.0

#tags: rendering,karma

= Karma Render Settings =

"""Configure Render Settings for Karma."""

The Karma Render Settings LOP creates [render vars|Node:lop/rendervar], a [render product|Node:lop/renderproduct] and a [render settings|Node:lop/rendersettings] primitive, configured for Karma.

@parameters

<!---
    Parameter references are taken from 
    lop/rendersettings.txt
    lop/rendervar.txt
    lop/renderproduct.txt
    lop/karmastandardrendervars
 --->

~~~ Render Settings Prim ~~~

RenderSettings Primitive Path:
    #id: primpath

    This node creates a `RenderSettings` prim with the configuration you set up using the parameters. This is the scene tree path where this node will create the `RenderSettings` prim.

RenderProducts Parent Primitive Path:
    #id: renderproductparentprimpath

    The location where the Render Products should be created.

RenderVar Parent Primitive Path:
    #id: rendervarsparentprimpath

    The location where the Render Vars should be created.

Output Picture:
    #id: picture

    An output image filename (usually an `.EXR` file), or `ip` which renders the image in [MPlay|/mplay].
    
    Include `$F` in the file name to insert the frame number. This is necessary when rendering animation. See [expressions in file names|/render/expressions] for more information.

:include rendersettings#camera:

:include rendersettings#res_mode:

:include rendersettings#resolution:

Engine Settings:
    #id: engine

    Select the rendering engine.

    CPU:
        Runs entirely on the CPU. Since this engine is entirely in software, it will _generally_ have more features and more correct output, however it is much slower than the [XPU engine|/solaris/karma_xpu].

    XPU:
        The [XPU engine|/solaris/karma_xpu] uses available CPU and GPU (graphics card hardware) resources. Since this engine inherits the limits of what can be done on a GPU, it will _generally_ lag behind the CPU engine in features, however it is much faster than the CPU engine.

Simplified Shading:
    #id: force_headlight

    Disable all shading and lighting (render with one headlight on the camera). This might be useful for preview purposes if a shaded view is too slow to render.

Primary Samples:
    #id: samplesperpixel

    When __Engine Settings__ is __CPU Parameters__, this is the number of ray-samples sent through each pixel. More samples will result in a
... (truncated, full doc is 61709 chars)
```

---

## lop/camera

```
= Camera =
#type: node
#context: lop
#internal: camera
#icon: OBJ/camera
#group: rendering
#since: 17.0

"""Adds a USD camera to the scene."""

:include _simple_prims#oview:

== Editing the camera in the viewport ==

:task: Enter the Camera state:

    Select the Camera node in the network, then in the viewport click the [Icon:TOOLS/handles] Handles tool, or press ((Enter)).

Look at |
    #width: 15%

    ((Shift + T)) |
        * Press ((Shift + T)) to show/hide the viewport "look at" handle.

        * Position the look-at handle to set a look-at constraint on the camera. Use the handles to orbit or elevate the camera relative to the target point.

        * This turns on the __Enable Look At__ parameter in the camera's Constraints section.

        * To constrain the camera to look at another USD prim, fill in the __Look at Primitive__ parameter.

Depth of field |
    ((Shift + F)) |
        * Press ((Shift + F)) to show a visualization of the focal plane in the view. The visualization shows a line where the plane intersects geometry.

        * When looking through a camera, you can ((Shift))-click or drag on a surface to move the focal plane to intersect that point.

        * When not at the camera from outside, you can use a handle on the focal plane to move it.

        [Image:/images/nodes/lop/camera_focal_plane.jpg]

F-Stop |
    ((Shift + A)) |
        * Press ((Shift + A)) to drop into __F-Stop__ control mode and use the mouse wheel to set the value. You can also ((Shift))-scroll for 0.1 steps and ((Ctrl))-scroll for 10 steps.


Exposure |
    ((Shift + E)) |
        * Press ((Shift + E)) to drop into exposure control mode and use the mouse wheel to set the value. You can also ((Shift))-scroll for 0.1 steps and ((Ctrl))-scroll for 10 steps.

Focal Length |
    ((Shift + S)) |
        * Press ((Shift + S)) to drop into __Focal Length__ control mode and use the mouse wheel to set the value. You can also ((Shift))-scroll for 0.1 steps and ((Ctrl))-scroll for 10 steps.

== Tips ==

* Cameras in USD are always "Y up", regardless of the stage's orientation, and look down the -Z axis.

* The parameters on this node are in millimeters. USD expects camera values to be in "tenths of a world unit", which means the parameters and values on the prim will sometimes be different.


@parameters

~~~ Frame Range/Subframes ~~~

:include _sampling#sampling_block/:

:include _sampling#subframe_sampling_block/:

~~~

:include _simple_prims#create_edit_block/:

== 
... (truncated, full doc is 9488 chars)
```

---

## lop/domelight

```
= Dome Light =
#type: node
#context: lop
#internal: domelight
#version: 3.0
#icon: SCENEGRAPH/domelight
#group: lighting
#since: 20.5

"""Creates or edits a USD Dome Light prim. A dome light emits light _inward_, simulating light coming from the sky/environment surrounding the scene."""

This version of the Dome Light LOP creates a USD prim with the `DomeLight_1` schema, as opposed to earlier versions of this asset which create a USD prim with the older `DomeLight` schema.

:include _simple_prims#oview:


== Environment maps ==

You will usually set the dome light to project a texture (_environment map_), such as a generic sky dome, or an IBL light probe (mirror-ball) reading taken on set.

* If you use a cube map, it must be a vertical cross.

* If you use a latitude-longitude map, you use should follow the OpenEXR specification for these kinds of environment maps. The following is from the OpenEXR documentation:

    :box: Latitude-Longitude Map
        #display: rounded
        #background: silver

        The environment is projected onto the image using polar coordinates (latitude and longitude).  A pixel's x coordinate corresponds to its longitude, and the y coordinate corresponds to its latitude. Pixel (`dataWindow.min.x`, `dataWindow.min.y`) has latitude `+pi/2` and longitude `+pi`; pixel (`dataWindow.max.x`, `dataWindow.max.y`) has latitude `-pi/2` and longitude `-pi`.

        In 3D space, latitudes `-pi/2` and `+pi/2` correspond to the negative and positive y direction.  Latitude `0`, longitude `0` points into positive z direction; and latitude `0`, longitude `pi/2` points into positive x direction.

        The size of the data window should be `2*N` by `N` pixels (width by height), where `N` can be any integer greater than `0`.


@parameters

~~~ Frame Range/Subframes ~~~

:include _sampling#sampling_block/:

:include _sampling#subframe_sampling_block/:

~~~

:include _simple_prims#create_edit_block/:

:include _simple_prims#create_prims/:

== Transform ==

:include _simple_prims#xform_block/:

~~~ Pivot Transform ~~~

:include _simple_prims#xform_pivot_block/:

~~~ Constraints ~~~

:include _simple_prims#xform_constraints_block/:

== Base Properties ==

:include _render_prims#light_base_props_block/:

Texture:
    #id: xn__texturefile_0ta

    File path to the texture file to use as an environment map.

Format:
    #id: xn__textureformat_9wa

    How the spherical environment is encoded in the texture image. The default, __Automatic__, tries 
... (truncated, full doc is 3643 chars)
```

---

## lop/null

```
= Null =
#type: node
#context: lop
#internal: null
#icon: COMMON/null
#group: util
#since: 17.0

"""This node does nothing. It can be useful to insert a Null into a network as a "fixed point" in the network that you can refer to by name in expressions/scripts."""

This node simply passes its input through to its output. If this node has an output but no input, it generates an empty stage with an empty active layer.

This can be useful as a way to refer to a point in the network by name. For example, you might want to refer to the final output of a node chain. If you just referred to whatever node was at the end of the chain right now, someone (or you) might come along layer and add more nodes, or delete the last node, or change its name because they changed what it does. Putting a Null at the end of the chain (or wherever you want to be able to reference the output by name) solves these problems.
```

---

## lop/switch

```
= Switch =
#type: node
#context: lop
#internal: switch
#icon: COMMON/switch
#group: util
#since: 17.0

"""Passes through one of several inputs, based on a parameter choice or expression."""


== Overview ==

Sometimes you will use this node to interactively switch between several options, but more often you will use an expression to compute which input to pass through, based on some other input(s).

You can choose the input based on its position in the multi-input, or by name.

* When __Choose Input__ is __By Index__, you choose the input by its position (from left to right, starting at 0) in the connections to this node's multi-input.

    * You can rearrange the inputs by clicking the [Icon:BUTTONS/list_reorderup] Move up button next to an item in the list of inputs below the parameters.

    * Any expression you write in the __Select Input__ field should evaluate to a whole number.

* When __Choose Input__ is __By Name__, you choose the input by its name.

    * To rename an input, click in the __Input Name__ column on the input row in the list of inputs below the parameters, type the new name, and press ((Enter)).

    * The __Input Name Default__ parameter contains an expression to generate names for inputs that you haven't named manually. The default (`opinput(".", @input)`) uses the name of the node connected to the input (this is the same name that is shown in __Input__ column in the list of inputs below the parameters).

    * Any expression you write in the __Select Input__ field should evaluate to a string.

* When __Choose Input__ is __By Pattern Matching__, you choose the input by assigning a pattern to each input, and comparing those patterns to the __Select Input__ value.

    * To set the pattern for each input, click in the __Match Pattern__ column of the list of inputs below the parameters.

    * This style of input selection is useful when a context option or other expression needs to drive the input, but not according to a simple one to one relationship.


== Tips ==

* If the value in the __Select Input__ field does not correspond to an actual input, this node outputs an *empty stage*. This does not generate any warning or error.

* Like the [Null LOP|Node:lop/null], this node shares the same stage object between the input and output, so using it adds no real performance penalty unless the expression is slow to evaluate.

* The __Select Input__ parameter is actually three different parameters, one for each possible value of the __Choo
... (truncated, full doc is 6077 chars)
```

---

## lop/layerbreak

```
= Layer Break =
#type: node
#context: lop
#internal: layerbreak
#icon: LOP/layerbreak
#since: 17.0

"""Starts a new active sublayer that subsequent nodes will edit, and indicates all previous layers will be discarded when saving to disk."""

:include /solaris/about_lops#breaks/:

```

---

## lop/restructurescenegraph

```
= Restructure Scene Graph =
#type: node
#context: lop
#internal: restructurescenegraph
#icon: LOP/restructurescenegraph
#group: util
#since: 19.0

"""This node has various operations for editing prim paths, variant sets, and composition arcs."""

This node allows for more destructive editing of the scene graph, in ways USD workflows normally discourage. When the layer stack is flattened into a single layer, this node can rename, remove, and reparent primitives and variants however. Hence the reason this node flattens the [Layer Stack|/solaris/glossary#layerstack]. However this will not allow you to rename primitives behind references or payloads.

== Tips ==

* See the help for the __Operation__ parm below to see what kinds of edits the node can perform.

* You can perform some of these operations interactively using the [Stage Manager|Node:lop/stagemanager], however using this node lets you select the prims using patterns.

* Currently this node doesn't work with For Each nodes. Even if you can craft a prim pattern that does what you need, looping in Python with an `Sdf.Changeblock` should always be more performant than a For Each block.

* This node is a wrapper for USD's `SdfCopySpec` and `Sdf.BatchNamespaceEdit` APIs.


== Rename primitives rules == (rename)

The following descriptions are only valid when you set the __Operation__ dropdown menu to __Rename Primitives__. Then, you will see __Old Name__ and __New Name__ parameters. In these fields you can use the `@name` token to refer to the current name of the prim, or you can use pattern matching where an asterisk (`*`) represents a any run of characters.

In __New Name__, you can also use the `@index` token to represent he position of the prim in the selection (for example, for the first selected prim `@index` will be `0`, for the second prim `@index` will be `1`, and so on).

The following examples show how to do different types of renaming using either `@name` or `*` patterns.

To do this ||
    Old Name ||
        New Name ||
Replace the old names with a new name and number |
    `@name` |
        `new_name@index`
Add a prefix |
    `@name` |
        `prefix_@name`
Add a suffix |
    `@name` |
        `@name_suffix`
Replace a prefix |
    `oldpre_*` |
        `newpre_*`
Replace the suffix of names that start with `char_` |
    `char_*_left` |
        `char_*_right`


@parameters

Flatten Node Input Layers:
    #id: flatteninput

    Automatically flatten all incoming sublayers. If this is off, you
... (truncated, full doc is 7281 chars)
```

---

## sop/scatter

```
= Scatter =

#type: node
#context: sop
#internal: scatter
#icon: SOP/scatter
#tags: copy, random, points
#bestbet: scatter
#version: 2.0
#since: 14.0
#verb_since: 16.5

"""Scatters new points randomly across a surface or through a volume."""

== Overview ==

This node distributes new points across the surface in a roughly uniform pattern and optionally attempts to limit clumping and holes.

For volume primitives, this node scatters points through the volume with a density proportional to the field value (with negative values giving zero probability).

You can use the generated points for a variety of purposes.
They may be used to specify birthing locations for particles,
template points for [copying|Node:sop/copy],
cell points for [fracturing geometry|Node:sop/voronoifracture],
or as queues for irradiance computations.

You can specify the density, the number of points per unit of area, (length for curves, volume for volumes and tetrahedra), optionally weighted by an attribute
to control the distribution over the surface of the geometry.  You can also scatter points with the density based on a texture map by scattering in texture space.

:include /shelf/scatter#includeme:

== Making scattered points stick on changing geometry == (stick)

If the input to the Scatter node changes on each frame, the output point positions and point numbers may change randomly from frame to frame.  There are a few
ways to avoid this for different scenarios.

:task: Stick scattered points to deforming geometry:

        See the Spiky Deforming Torus example.  If the geometry doesn't change in topology, the points can be scattered once on static "rest" geometry, and deformed on each frame using the [Attribute Interpolate node|Node:sop/attribinterpolate].

        <!-- [Image:/images/nodes/sop/scatter_deform_network.png] -->

        # Connect the static "rest" geometry to the input of the Scatter node,

        # Turn on the __Prim Num Attribute__ and __Prim UVW Attribute__ output options,

        # Connect the output of Scatter to the first input of Attribute Interpolate, and

        # Connect the deforming geometry to the second input of Attribute Interpolate.

        The Scatter node will only cook once, and the Attribute Interpolate node will cook on every frame to move the points to the corresponding positions on the deformed geometry.

:task:Keep consistent points when geometry is cut, subdivided, or replaced with higher resolution model:

        See the Door With Polk
... (truncated, full doc is 19959 chars)
```

---

## sop/attribwrangle

```
= Attribute Wrangle =

#type: node
#context: sop
#internal: attribwrangle
#icon: SOP/attribwrangle
#tags: attrs, vex, tech
#since: 12.5

"""Runs a VEX snippet to modify attribute values."""

== Overview ==

This is a very powerful, low-level node that lets experts who are
familiar with VEX tweak attributes using code.

This node corresponds to the [Attribute VOP SOP|Node:sop/attribvop],
but uses a textual VEX snippet instead of a VOP network.

WARNING:
    This node requires that you understand the [vex language|/vex/].
    It is very easy to write incorrect code using this node.

This node _runs the snippet on the detail or every point/primitive/vertex_
(depending on the __Class__ parameter) in the input geometry.
The snippet can edit the input geometry by changing attributes.
It can access information from other geometry using attributes and VEX functions.

* Press ((MMB)) on the node to see any error output from the snippet.

* You can use the VEX function `ch` to evaluate parameters.
  The path is relative to this node (`ch("parm")` will evaluate the parameter `parm` on this node). This evaluation will be done at the current time.

* Unlike the [Attrib Create SOP|Node:sop/attribcreate], this does not use local variables.
  Further, all backtick expressions and `$F` variables will be evaluated at frame 1,
  not the current time.
  Use `@Frame`, `@Time`, or `@TimeInc` instead.


== Syntax ==

:include wrangle_syntax:


@parameters

== Code ==

Group:
    A subset of points in the input geometry to run the program on.
    Leave this blank to affect all points in the input.

Group Type:
    What the group is made of.

:include _run_over:

:include pointwrangle#snippet:

Attributes to Create:
    Only create attributes if their names match this pattern.
    The default pattern allows any attribute to be created.
    
    You can restrict the created attributes by replacing the `*` with a list of allowed names.

    Bound attributes, such as `vtxnum`, cannot be created and will be ignored.

:include /vex/_enforce_prototypes:

:include /vex/_strictvariables:


== Bindings ==

Autobind by Name:
    Automatically bind attributes to parameters by name.
    If for some reason you need CVEX parameters to have different names
    than the corresponding attributes,
    turn this off and use the __Number of bindings__ parameter to set up
    mappings between __Attribute name__ and __VEX parameter__.

    Integer attributes will bind to integer parameters.
    Float a
... (truncated, full doc is 5137 chars)
```

---

## sop/copytopoints

```
= Copy to Points =

#type: node
#context: sop
#internal: copytopoints
#icon: SOP/copytopoints
#tags: copy, model
#version: 2.0
#since: 18.0
#verb_since: 18.0

"""Copies geometry in the first input onto the points of the second input."""


== Overview ==

This is very useful for populating scenes with repeated elements such as trees, buildings, or snowflakes with full control over the placement of the copies.

TIP:
    To simply create multiple copies of geometry without needing target points, use [Duplicate|Node:sop/duplicate].

For example, you can arrange copies in a spherical shape by copying them onto the points of polygonal sphere. Or you could [scatter|Node:sop/scatter] points across a terrain geometry and copy trees onto the points.

Note that this node creates additional geometry in the scene for each copy. If you have very large numbers of copies, you may want to investigate [render-time instancing|/copy/instancing] or [Alembic, packed primitives, or polysoups|/copy/packed_and_soups] to reduce memory usage.

For more information, see [copying to points|/copy/copytopoints] in the [copying and instancing|/copy/] chapter.


== Varying the copies == (instanceattrs)

* When you copy or instance geometry onto points, Houdini looks for specific attributes on the destination points to customize each copy/instance. For example, you can change the scale of each copy by creating a `pscale` attribute on the points you copy onto. See [instancing point attributes|/copy/instanceattrs].

* If you need to copy different source geometry to different points, the __Piece Attribute__ option gives that ability if all geometry to be copied is in the source geometry input, (the first input).

* If you need more control over the copies, you can [use a For-Each loop|/copy/copytopoints#foreach] to process each copy individually.


== How to == (howto)
         
# Click the [Icon:SOP/copytopoints] Copy to Points tool on the __Modify__ tab.

# Select the source geometry you want to copy and press ((Enter)).

# Select the target geometry on whose points to instantiate the source and press ((Enter)).

[Image:/images/shelf/copy.jpg]


@parameters

Source Group:
    #id: sourcegroup

    A subset of the source (first input) primitives or points to copy from.
    You can create groups with the [Group SOP|Node:sop/group].

Source Group Type:
    #id: sourcegrouptype

    The type of group that __Source Group__ specifies.

    If __Guess from Group__ is specified and the group type 
... (truncated, full doc is 5729 chars)
```

---

## sop/grid

```
= Grid =

#type: node
#context: sop
#internal: grid
#icon: SOP/grid
#tags: create, surface, model

"""Creates planar geometry."""

The plane can be a
mesh, Bezier and NURBS surfaces, or multiple lines using open polygons.

:include /shelf/grid#includeme:

@parameters

Primitive Type:
    Type of Geometry to create. In the case of Points, no geometry is
    created. Instead, free floating points are created in the same
    positions as they would be in a surface.

Connectivity:
    Applies to Polygons and Meshes only.

    Rows:
        Creates horizontal lines, which are open polygons.

    Columns:
        Creates vertical lines, which are open polygons.

    Rows & Cols:
        Both Rows and Columns. All polygons are open.

    Triangles:
        Build the grid with Triangles.

    Quads:
        Default grid connection is four-sided quadrilaterals.

    Alternating Triangles:
        Build the grid with alternating triangles. Each four sided quadrilateral is divided in half making two back to back triangles, with the dividing lines alternating in direction.

    Reverse Triangles:
        Build the grid with reverse triangles. Each four sided quadrilateral is divided in half making two back to back triangles, with the dividing lines all facing the same direction.

Orientation:
    Orientation plane of grid.

Size:
    Width and Height of the grid.

Center:
    #id: t

    Position of the center of the grid.

Rotate:
    #id: r

    Rotation about the center of the grid.

Rows:
    #id: rows

    Number of rows in the grid or hull.

Columns:
    #id: cols

    Number of columns in the grid or hull.

U Order:
    #id: orderu

    The order of NURBS or Bezier surface in the U direction.

V Order:
    #id: orderv

    The order of NURBS or Bezier surface in the V direction.

End-point interpolate in U:
    #id: interpu

    Extends the surface to touch the end points in the U
    direction.

End-point interpolate in V:
    #id: interpv

    Extends the surface to touch the end points in the V
    direction.

```

---

## sop/null

```
#type: node
#context: sop
#internal: null
#icon: COMMON/null

#tags: network, util

= Null =

"""This node passes its input through to its output unchanged. It can act as a fixed place in the network for path references."""


== Overview ==

Some common uses of the Null node:

* If you point a path reference to a node in the middle of a network, you may later need to add more nodes below the referenced node to further process the geometry, and then you would have to update all the references to the original node to point to the new node that now outputs the "finished" geometry. Instead, it is good practice to insert a Null SOP below the node whose output geometry you want to grab, and then reference the Null SOP. That way you can add more nodes above the Null without having to change any references to the Null.

* You can crate [spare parameters|/network/spare] on a Null and channel reference them from elsewhere in the network as a simple way to add some parameters to control things in the network.

TIP:
    Adding a Null to the network does not increase memory usage (unless you turn on the __Cache Input__ parameter).

:vimeo: Null SOP
    #id: 406959324


@parameters

Copy Input:
    #id: copyinput 

    When this is on, the Null cooks its input, but not copy the result.  This is useful if you want to enforce the cooking of a node at a certain time, but don't need the result. You can use a [Merge SOP|Node:sop/merge] to collect dependencies into a single input this way.

Cache Input:
    The Null caches its input in memory. This makes it possible to unload the Null's input.


@related

- [Node:sop/object_merge]


```

---

## sop/merge

```
= Merge =

#type: node
#context: sop
#internal: merge
#icon: SOP/merge
#tags: merge

"""Merges geometry from its inputs."""

This node merges together the geometry from its inputs
into a single stream of geometry, which you can then send through other nodes.
If you need to continue distinguishing different parts
of the merged geometry later, try using the [Group node|Node:sop/group]
to put the input geometries into groups before merging them.

You can merge together a maximum of 9999 inputs.

NOTE:
    Bypassing this node causes it to only export the first input. It will not compute the merged objects.
    
@related

- [Node:sop/object_merge]

```

---

