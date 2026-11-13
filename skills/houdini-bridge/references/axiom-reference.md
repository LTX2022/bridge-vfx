# Axiom 4 Official Documentation
> Source: https://theoryaccelerated.notion.site/axiom-4 (Theory Accelerated / Axiom 4)
> Auto-fetched 2026-08-03. Official docs for the Axiom GPU fluid solver (axiom_solver::4.0).
> Key pages: Getting Started / Sourcing / Simulation / Combustion / Output / Settings / Memory Management / Environment Variables / Trouble Shooting / Profiling / What's New In 4.0/4.1

# Axiom 4 Official Documentation (Axiom 4 pages)

---

## Getting Started
  This page will go over the basics of Axiom and all the various setting you need to know about before creating your first simulation.
## Making A New Solver Node
  To create a new solver node you need to be in the SOP context in Houdini. Press tab to bring up the node menu and search for “Axiom Solver” in the dialogue. Then click anywhere to drop the solver down. 
📌 Axiom is not available in DOPs. It is implemented as a SOP node.
## Solver Tab
### Time
  By default, the solver will set the start frame to the first frame on your timeline. You can change this to whatever start frame you want.
  Time Scale will allow you to make your simulations faster or slower by globally changing the length of time of each simulation step. 
  If you have a fast-moving simulation you can add more substeps to make the motion resolve better. Doing this will slow down the solver.
### Solver
  Mode will let you set what fluid simulation algorithm you want to use. Traditional will use an algorithm that acts like classic old school fluid dynamics. Reflection will use the new reflection-advection algorithm to try and preserve energy that is usually lost with the traditional mode. Reflection single step is a faster version of the reflection mode but is not as accurate. 
  Division size will control the voxel size of the simulation grid. Smaller values will make the grid higher resolution.
  The voxel parameter controls the starting number of voxels the simulation will use. This is not a hard limit and the solver will increase it if it needs more. You can set this value to be higher if you know you will be working with a large simulation but generally leaving it on the default is fine.
📌 Making the voxels value higher will use more memory. By default with 32m voxels the solver will need 2.37GB of memory. 
### Info
  The info section will give you basic information about the current simulation such as what device is being used and how many voxles are in use.
  Allocated memory will tell you how much memory the solver is currently using and used memory will tell you out of that allocation how much of the memory is being used.
📌 Keep in mind this is not the total amount of memory your device has or can use. The solver does not need to be using all of your device’s memory if it does not need to. 

---

## Sourcing
  There are three ways to source with Axiom, VDBs, Houdini Height Fields, and primitive shapes that come with the Axiom toolset called Source Shapes.
## Settings
  You will see all of the fields you can source into here.
  These settings control the global sourcing independent of the type of source being used however some setting are unique to certain types such as VDBs.
  For each of the fields you can choose how the sources are contributed to the field. 
  Mask Name is the name of the source used to mask the source operation. It is not a simulation field. For the mask to work in the example above you must have a source VDB named “density” input to the solver. This can be left blank if you do not want to mask the source operation.
  Scale is a multiplier of the source’s values.
  Blend Mode controls how values are contributed to the field.
    - Add will add the source field to the sim field.
    - Replace will replace any voxel values where the source overlaps with the source’s value.
    - Maximum will choose the value of the field that has the higher value.
    - Pull will increase the value toward the source value but not exceed the source value.
    - Blend will do a linear interpolation between the target field and the source.
  Acceleration is the speed of effect of the Blend or Pull mode.
  Time Step controls the rate at which the source operation occurs.
    - Time Step will add the value of the input per second.
    - Frame Step will add the value of the input per frame.
    - None will add the value every time the solver cooks including substeps.
    - Solver Time Step is the same as time step but will also take the solver time scale into consideration.
    - Solver Frame Step is the same as frame step but will also take the solver time scale into consideration.
  Activation allows you to use this source to activate regions in its area of effect. This does not make the field an activation field. 
## VDBs
  You can connect VDBs directly into the first input of the solver. You can make these sources any way you want. It can be sourced using OpenVDB or on the GPU using NanoVDB which is on by default.
### Naming
  The solver will only accept these names for default sourcing. It is case-sensitive.
  - density - float scalar fog
  - temperature - float scalar fog
  - fuel - float scalar fog
  - vel - float vector 
  - pressure - float scalar fog
  - color - float vector 
  - Cd - float vector 
  - aux1 - float scalar fog
  - aux2 - float scalar fog
  - sink - float scalar fog / float scalar sdf
  - active - float scalar fog / float scalar sdf
  - collision - float scalar fog / float scalar sdf
  - collisionTemperature - float scalar fog
  - collisionVel - float vector 
📌 
    For vector type fields you can source individual components by naming them accordingly. For example you can source into the x component of velocity by naming a float VDB “vel.x”.
### Custom
  You can also source using any VDBs if you specify it by name and tell it which field to source into. You can have a virtually infinite number of these.
  For example you can have a VDB named “banana” that is masked by another VDB called “apple” that is sourcing into the density field. The names can be anything you want as long as they are unique and don’t conflict with standard source names.
  These can be used to source extra velocity fields for creating custom forces. 
  This is also useful if you need to have differnet VDBs be sourced with their own blend modes seperate from the default ones.  
📌 
    Make sure the VDB type matches the field. You can’t source a vector VDB into a float field for example. 
## Height Fields
  You can plug height fields directly into the first input where you also plug-in your VDB sources. You can also combine them with your VDB sources.
📌 Node that unlike source volumes you do not need to convert the height fields from Houdini volumes to VDBs. The solver is able to work directly with the Houdini volumes if they are named “height” and are a height field. You can convert them yourself however be careful as zero values tend to be pruned and may give you unexpected results because the bounds of the high field may change. 
## Source Shapes
  The Source Shape node gives you primitive shapes to source with. The advantage to using these shapes over VDBs is that they are much faster to source from. You plug these into the second input on the solver.
### Types
  Source shapes can act as sources, colliders, sinks, and activators and you can choose from a list of many different shape types. 
  The Activation option allows you to have the source shape active the region it occupies. The Activation mode does this by default but normally you want your source to activate as well. Sometimes when using the source shape as a custom force you do not because it might occupy a large area. 
  One other important feature is the ability to invert source shapes in the collisions and sink modes to create max bounds for your sim. Instead of affecting everything inside the shape, they affect everything on the outside.
### Sourcing
  You can choose which fields you want the shape to source into.
  You can also choose if you want to use the solver’s source settings or pick your own and a per shape basis.
📌 
    Remember that source shapes are sourced in the order they are input so some later shapes may overwrite values of previous shapes if the blend mode is set to replace for example. 
📌 
    If you are using a source shape purely as a force remember to disable sourcing into the other fields such as density, temperature, fuel, etc. 
### Transform
  You can place and transform the source shape using the viewport handle.
  You can also inherit the size and position of a piece of geometry by plugging it into the input on the source shape node. You can also have it approximate its orientation using the match input orientation toggle.
### Inherited Velocity
  You can have the motion of the source shapes affect the simulation by enabling use inherited velocity. The Ignore Time Step option will not scale the velocity resulting from motion by the simulation time step. This is useful if you want to source velocity with the replace blend mode and have it keep its value in terms of velocity per second.
#### Instancing 
  You can instance source shapes to particles however please note that they will not use the velocity attribute on the particles to affect the simulation. You can however modify the directional force attribute of the source shape primitive on a per point basis to achieve a similar effect.
### Noise
  Source shapes are limited in their simple shapes. To help this the tool gives the option to modify the shape using noise fields to make the source more organic. You can also source velocity noise here. Value noise will cut away from the shape, deformation will change the shape, velocity adds noise to the velocity of the source.
### Force
  Source shapes also let you add in basic forces such as noise, direction force, radial force, and spin. This is very useful to sculpt a simulation by region.
## Activation Fields
  Axiom will use the density field in order to know where active regions of the simulation are. If nothing is sourced into density the simulation will not expand. You can however set temperature and fuel to be activation fields in the solver’s sparse settings.
## Advanced
  Some advanced settings for sourcing can be found under the input tab in the settings tab. 
### NanoVDB
  By default Axiom uses NanoVDB to source volumes on the GPU. This is much much faster than sourcing on CPU then uploading to the GPU. 
### Max Source Buffers
  To speed up sourcing you can queue up multiple source volumes for the solver to sample. With the default 4 you can queue up 4 source operation without any delay in source processing. If you have more than 4 it will need to wait for one to finish before the next one can be queued.
### Max Source Shapes
  By default Axiom can source a maximum number of 128 source shapes. If you need more you can set this value higher in the advanced settings.

---

## Simulation
  In this tab, you can control all the settings that drive the look of your sim.
## Settings
  Controls are separated into two sections. At the top, you have a list of sliders and toggles that let you enable and change the strength of the various forces.
  Below you have extra settings tabs for each of the forces. Some forces are simple enough that all they need is a strength slider. Some are more advanced, like turbulence, that has many additional options.
### Control Ramps
  Some forces also let you control them with a ramp based on the value of a field, the speed of velocity, position along an axis, or a custom field. Dissipation, for example, has a ramp on by default. The hotter the temperature, the less dissipation you will get.
  To control a force with a custom field you need to create a float VDB with the name control1, control2, or control3 and include it with the rest of your VDB sources. Then choose the corresponding option in the Control Field’s Field parameter. 
  The field can have a range of values to scale the effect of the force in different regions. The ramp will allow you to remap the range of values of the source control field just like any other field. 
📌 The control fields will not be included in the simulation and will not be output. It’s just a temporary utility field used to drive forces. 
### Time Scale
  Percent-based forces such as dissipation and cooling rate work based on the idea that some percentage of value is lost per time increment. The time increment is defined by the menu next to these parameters. You can choose to have the force work on a percent per second, per frame, none (the full amount each simulation time step), or also keep the time scale of the simulation in mind. This is helpful if you have a force that needs to react faster than some percentage lost per second.

---

## Combustion
  For pyrotechnic-type effects you can enable combustion by using the burn option in the forces tab.
## Settings
  The burn option controls the rate at which fuel is removed from the simulation.
  The combustion tab then lets you set the rules for the resulting reaction.
### Ignition
  The Ignition Temperature controls at what temperature fuel will be allowed to burn, This can also be controlled with a control ramp if you need to do something more complex like only letting fuel burn if it is moving very slowly.
  Advect Fuel allows the fuel in the simulation be advected with the rest of the fields. Sometimes with an effect like burning wood you may want to have your fuel stay static, but with a flame thrower fuel material is shot out and mixes with the air.
  Burn Inefficiency controls how much of the burnt fuel is actually removed from the simulation. This is helpful if you want fuel to burn but not actually be removed from the sim making it last longer without needing to actually inject more fuel.
  Threshold allows you to only burn fuel values below this amount. Any fuel value above the threshold will not be allowed to ignite until it diffuses naturally and goes below this value. This is good for doing air-fuel mixture type effects.
### Emission
  For every unit of fuel burnt, how much of each of these values do you want to introduce into the simulation? Density emits density, temperature emits temperature, and pressure emits pressure that causes your simulation to expand outwards. Be careful not to add in too much pressure or else the simulation might expand too fast.

---

## Output
  In this tab, you can control what fields the solver will output and provide various settings to control the resolution and compression.
## Settings
  You can choose to output simulation fields as VDBs and/or a visualizer for the sparse data structure for debugging purposes.
### Fields
  You can choose what specific fields get output. Choosing fewer fields will improve the speed of the simulation. Typically only output density when trying to dial in settings, then re-enable the others when it’s time to cache out the final result.
  This is also the place you would enable some features like color and rest.
#### Compression
  You can choose to output at a lower resolution. Sometimes you may not need a full resolution temperature or velocity field for rendering. The filter will determine how to downsample a lower resolution grid. Index will skip voxels and write out values at intervals, average will average out a group of voxels to assign to a lower resolution grid.
  The Mask Field will mask by the chosen field.
  Deactivate Empty Voxels will not output any voxel that has a value below the simulation threshold value.
  16 Bit Write To Disk will compress the volume when it is written out to a file. This will help save on disk space usage without losing much quality if anything. This also tells the GPU to copy from device to host as 16-bit float values.
#### Visualizer
  If you don't need to see the field in the viewport you can mark it as invisible or use one of the other visualization modes. 
#### Type Specific Options
  Specific options that control the characteristics of some fields when they are prepared for output.
  Velocity
  Velocity stage lets you pick when to output velocity. You can choose to output velocity post-advection or the corrected version after the pressure solve step. 
  Rest
  When you choose to output a rest field you get additional settings.
  If you disable dual rest the solver will output only one rest field and it will not reset it during the simulation. Dual rest will alternate between resetting each of the rest fields based on the frame length. It will also output an axiom_dualRestLerp detail attribute to blend between them in the shader or in SOPs when post-processing. The longer the frame length the longer it will be between resets.
  The advection scale controls how much the rest field will be advected compared to the normal fields.
### Data Structure
  You can output a visualizer for the octree Axiom uses to debug if things seems wrong. This is a good tool to check if regions you don't expect to be active are and vice versa.
## Advanced
  Less commonly used output settings can be found under the Advanced tab of the solver.
  Performance lets you choose if you want to output the current frames simulation while the next frame is simulating in parallel or if the output should happen after the simulation. Parallel will significantly increase the solver performance. 
📌 Simulating in parallel can cause issues if you do not clamp your caches sources. If there isn't a frame cached for the frame after the last frame of your sim it may result in an error. Try adding a time shift node before you source and set the clamp range to the range of your caches.
## Retime & Particle Advection Suggestions
  If you plan to use the solver's output velocity to do retiming or particle advection it is highly recommended to change the velocity stage to Corrected, change velocity compression to 1/1, and to disable the mask. This is so that you have the complete and highest quality version of velocity that will give the best results for these types of operations. 

---

## Settings
  Here you can find more advanced settings that you will hopefully rarely need to touch.
## Solver
  Field precision lets you choose a higher or lower field precision. 16-bit will be less precise, but will use 36% less total memory compared to 32-bit. 
  Voxel limit behavior allows the solver to increase the amount of allocated memory mid-simulation if the solver needs it. By default it will add 20% more memory if the simulation uses 95% of the current memory allocation. You can also tell the solver to use the voxel limit you set as a hard limit. 
  Debug verbosity will let the solver print out debug information to the console. When you are encountering a problem this can be useful to see why the solver might have failed or errored.
## Sparse
### Data Structure
  The leaf size controls the size of individual leaves which are the base blocks of voxels the grid is made up of. Generally, you should leave it on 16^3 but if you have a very large and detailed simulation you should consider switching to 32^3.
  The number of levels controls how many hierarchy levels the octree has. Generally you should leave it on 6, but if you have a sim that is extremely large and exceeds the 32 root nodes that are allowed you can increase this.
### Leaves
  Remove inactive leaves will remove any leaves whose voxels values fall below the threshold value. We recommend always leaving this on.
  Sort leaves will reorganize the data structure each time step to run more efficiently. You don't really need to worry about this, simply leave it on at all times.
  Value threshold is the value below which voxels are considered inactive. This is used for the activation and deactivations of leaves to enable a dynamically changing domain.
### Activation Fields
  This is actually very useful and probably the main reason you would come to the settings tab. By default, the solver will require a density field to know what leaves are active. No density means no simulation. However, if you want to have a sim that does not use density and only uses temperature for example you will need to set it to another mode to recognize temperature or fuel as an activation field.
### Margins / Bounds
  Margins are important for allowing the simulation to expand and grow outwards. What happens is the solver takes all the active leaves and then adds a layer of empty leaves around them to allow density, temperature, and fuel to move into new spaces. Think of this as breathing room for your simulation.
  A margin iterations of 0 will not allow the sim to move past its initial bounds.
  Velocity iterations allow for extra padding in the direction of fast-moving voxels. This is good for removing sparse artifacts.
## Compute
  Memory allocation has options for what memory the device you chose is allowed to access. When using Metal or Cuda a device can used shared memory which is the system ram in addition to your GPU’s memory. This option is not available with OpenCL. 
  The memory buffer is an amount of memory expressed in MBs that the solver will keep free on your device. If you have an 8GB GPU and set the memory buffer to 1000MB then the total amount of memory the solver can use on your device is 7GB. 

---

## Memory Management
  Volumes use a large amount of memory and it’s important to keep your device’s limitations in mind.
## Cleaning Memory Usage
  The solver will retain allocated memory until the solver node is disabled with the Enable toggle, deleted from your scene, or Houdini is closed. 
## Voxels Count & Memory Relationship 
  When simulating with 32-bit fields, Axiom will use 1GB of memory for every 13m voxels you allocate. With a 8GB GPU you will be able to simulate 91m voxels under ideal conditions. 
📌 By default Axiom reserves 1GB of memory on your device as to not accidentally fully saturate it and lock up your computer. You can control this with the Advanced → Compute → Memory Buffer parameter on the solver node.
  Your computer will usually be using memory for tasks other than simulating so you will typically have less than the total amount of device memory available to you. 
## Shared Memory 
  If you are using Metal or Cuda your GPU has access to your system memory as well as its own. The solver will try to use all the available memory on your GPU before starting to use your system memory. 
📌 Please note that when the solver uses shared memory it will be slower as it needs to access memory over PCIe. 
📌 
    You can disable this behavior and have your device to only use device memory by using the Advanced → Compute → Memory Allocation parameter on the solver node.
## GPU Rendering & Simulating In Parellel 
  It is recommended to not have a live render and Axiom simulation active at the same time. Unless you have a very large amount of GPU memory, doing both at the same time may cause the two processes to compete for resources and may result in instability. 
## Viewport
  Rendering volumes in Houdini’s or any other DCC’s viewport can use a large amount of memory. If you want to maximize the amount of memory that Axiom can use you can try reducing the viewport volume resolution or unload heavy assets when simulating. 

---

## Environment Variables
  Some behaviors of the solver can be set via environment variable that will override settings on the UI. This can be useful in a studio environment to make sure all users use the desired settings for a project. 
## Solver
  AXIOM_SOLVER_SOURCE_USE_NANOVDB
    Value: Boolean - Default: ON
    Sets if NanoVDB should be used when sourcing VDBs. Setting this t 0 means sourcing will occur on CPU then the result copied to the compute device.
  AXIOM_COLLISION_MASK
    Value: Boolean - Default: ON
    Masks collision fields such as sourceVelocity and sourceTemperature by the collision source volume.
  AXIOM_KERNEL_JACOBI_ORIGINAL
    Value: Boolean - Default: OFF
    Will use an un-optimized version of the Jacobi kernel.
## Compute
  AXIOM_COMPUTE_FORCE_FINISH 
    Value: Boolean - Default: OFF
    Forces the solver to finish each compute task immediately after it is queued. This is for debugging and should not be enable for normal use as it negatively impacts performance. 
### API
  AXIOM_COMPUTE_API_USE_OPENCL 
    Value: Boolean - Default: OFF
    Has the solver use OpenCL. This overrides the user API parameter option.
  AXIOM_COMPUTE_API_USE_METAL
    Value: Boolean - Default: OFF
    Has the solver use Metal. This overrides the user API parameter option.
  AXIOM_COMPUTE_API_USE_CUDA
    Value: Boolean - Default: OFF
    Has the solver use Cuda. This overrides the user API parameter option.
#### OpenCL
  AXIOM_COMPUTE_OCL_EXTRA_COMPILER_OPTIONS
    Value: String - Default: “”
    Add extra compiler options for OpenCL. For example “-cl-fp32-correctly-rounded-divide-sqrt”, “-cl-fast-relaxed-math”, “-cl-unsafe-math-optimizations”. You can add multiple separated by a space character.
  AXIOM_COMPUTE_OCL_USE_CPU_DEVICES
    Value: Boolean - Default: ON
    Enables or disables the use of CPU devices.
  AXIOM_COMPUTE_OCL_USE_GPU_DEVICES
    Value: Boolean - Default: ON
    Enables or disables the use of GPU devices.
  AXIOM_COMPUTE_OCL_USE_UNIFIED_MEMORY_DEVICES
    Value: Boolean - Default: ON
    Enables or disables the use of unified memory devices such as CPUs or integrated GPUs.
  AXIOM_COMPUTE_OCL_USE_INTEL_INTERGRATED_GRAPHICS_DEVICES
    Value: Boolean - Default: OFF
    Enables or disables the use of Intel integrated GPUs.
  AXIOM_OCL_FLOAT_CONSTANTS_USE_CONST 
    Value: Boolean - Default: OFF
    Have constants use the “const” qualifier instead of “__constant” when declared in shader code.
  AXIOM_COMPUTE_OCL_AMD_GPU_OPTIONS
    Value: Boolean - Default: ON
    Adds additional flags for AMD GPUs.
  AXIOM_COMPUTE_OCL_PROFILE
    Value: Boolean - Default: ON
    Allows for profiling of OpenCL kernels.
  AXIOM_COMPUTE_OCL_ALLOW_SHARED_MEMORY
    Value: Boolean - Default: OFF
    Allows for shared memory when using OpenCL.
#### Metal
  AXIOM_COMPUTE_METAL_LIBRARY_FILE_PATH
    Value: String - Default: “$AXIOM/compute/metal”
    You can have axiom use a different Metal library.
#### Cuda
  AXIOM_COMPUTE_CUDA_DO_DRIVER_VERSION_CHECK
    Value: Boolean - Default: OFF
    Will have the driver perform a compatibility check. 
  AXIOM_COMPUTE_CUDA_CHECK_ERROR_AFTER_SYNC
    Value: Boolean - Default: OFF
    Will force a synchronize before each error check.
### Memory
  AXIOM_COMPUTE_USE_SHARED_MEMORY
    Value: Boolean - Default: ON
    Uses shared memory in addition to device memory. This overrides the user parameter option.
  AXIOM_COMPUTE_UNIFIED_MEMORY_DEVICES_USE_DEVICE_BUFFERS 
    Value: Boolean - Default: OFF
    Allocates device memory type buffers even if the device is a unified memory device that would normally use shared memory.
### Device
  AXIOM_COMPUTE_DEVICE_NAME 
    Value: String - Default: None
    You can set what device the solver should prefer to use. You can get the name by using the manual device drop-down menu on the solver. This can only be one device. This only has an effect if you are using the GPU or CPU device type menu options. The manual and index options override this variable.
  AXIOM_COMPUTE_DEVICE_INDEX
    Value: Integer - Default: None
    If you have multiple GPUs in your computer you can use this to set which GPU you prefer the solver to use. You set a number from 0 onwards. This only has an effect if you are using the GPU or CPU device type menu options. The manual and index options override this variable.
  AXIOM_COMPUTE_DEVICE_NAME_BLACK_LIST
    Value: String - Default: “”
    You can set what devices the solver should never use. You can get the names by using the manual device drop-down menu on the solver. Multiple names can be set if they are comma-separated.
## Threading
  AXIOM_THREAD_COUNT
    Value: Integer - Default:  System Thread Count
    Lets you set the number of CPU threads to use when performing non-compute operations.
  AXIOM_THREAD_USE_TBB
    Value: Boolean - Default: ON
    You can have it use Intel’s TBB threading library when performing multithreaded operations instead of the default standard library. If disabled it will use the C++ standard library’s threading methods.
  AXIOM_THREAD_TBB_USE_ARENA
    Value: Boolean - Default: OFF
    Will use a TBB Task Arena to manage the thread pool. 
  AXIOM_THREAD_TBB_USE_PARALLEL_FOR
    Value: Boolean - Default: OFF
    Will use a TBB Parallel For primitive to dispatch work. The default if this is off is to use the TBB Task Group primitive.
## Licensing
  AXIOM_LICENSE_PORT or THEORY_LICENSE_PORT
    Value: Integer - Default:  8086
    Port for the local license server.
  AXIOM_LICENSE_HOST or THEORY_LICENSE_HOST
    Value: String - Default:  None
    Hostname for the local license server.
  AXIOM_LICENSE_IP or THEORY_LICENSE_IP
    Value: String - Default:  None
    Host IP address for the local license server.
  AXIOM_LICENSE_FILE or THEORY_LICENSE_FILE
    Value: String File Path - Default:  None
    For manually setting a license file.
  AXIOM_LICENSE_KEY
    Value: String File Path - Default:  None
    For setting a timed key.
  AXIOM_LICENSE_TIMEOUT
    Value: Integer - Default:  60
    You can set the license timeout for connecting to a server in terms of seconds.
  AXIOM_LICENSE_HEADLESS_ONLY_USES_HEADLESS
    Value: Boolean - Default: OFF
    This won't let any computer with this variable set to 1 use a GUI licenses if Houdini is run headlessly.
  AXIOM_LICENSE_VERBOSE
    Value: Boolean - Default: OFF
    Will have the solver print more verbose license related messages to the terminal.
## Debug
  AXIOM_LOG_FILE_PATH
    Value: String File Path - Default:  None
    A file path to write the console output to.
  AXIOM_LOG_CONSOLE_OUTPUT
    Value: Boolean - Default: ON
    Will disable any printing to the terminal / console.
  AXIOM_PROFILE_INBETWEEN_FRAMES
    Value: Boolean - Default: OFF
    Will show a timer for the time in-between invoking the cook method on this node in Houdini.

---

## Picking A Device
  When using the solver it will default to using any available GPU as long as it has enough memory to support the number of voxels you have selected. If it can not, it will fall back to using the next best device that has enough memory.
📌 Choosing a specific device on a system does not guarantee that that device will be used, it is just a suggestion to the solver. Reasons it may not pick a device you choose could be an out of date driver, lack of memory resources, or incompatibility.
## Compute API
  API lets you choose what compute API you want the solver to use. Auto is the default and will choose the best API for your platform. OpenCL will work on most GPUs and CPUs. Metal is only available on macOS and will perform faster compared to OpenCL. Cuda is only usable with Nvidia GPUs.
## Name
  If you have multiple devices such as two GPUs you may want to ask the solver to use one over the other. You can select a device by name by choosing name in the  device drop-down menu. You will see a device name field appear. You can choose a device from this field’s drop-down menu.
📌 
    This does not guarantee the device will be chosen. If it encounters an issue during initialization the solver will try another as a backup.
## Index
  In some situations you may want to choose a device based on an index rather than a name. The order of the devices will vary from system to system, but you can ask the solver to use the first, second, third, etc. GPU on a system to run multiple simulations in parallel.

---

## Trouble Shooting
  How you can help us help you! If you experience a sudden crashes it will be helpful to provide us a log file to inspect what was going on at the time of a crash.
## Log File 
  The first thing you should do is set an environment variable to tell Axiom where to save the log file. This can be in any folder that exists.
```
AXIOM_LOG_FILE_PATH = /path/to/log/file.txt
```
  This environment variable should be set in your houdini.env file which can be found here on your OS.
  Windows
    C:\Users\USERNAME\Documents\houdini##\houdini.env
  macOS
    /⁨Users⁩/⁨USERNAME/⁨Library⁩/Preferences⁩/⁨houdini⁩/##⁩/houdini.env
📌 On macOS you may need to use Finder’s go to folder feature to get to this directory.
  Linux
    /home/USERNAME/houdini##/houdini.env
## Debug Mode
  Next, restart Houdini and create a solver node or open the file with the solver node that caused the crash before.
📌 If Houdini crashes immediately, try setting Houdini to manual mode from auto-update in the lower right hand corner of Houdini’s UI.
  On the solver node under the settings tab you will find a parameter called Debug Verbosity. This  allows the solver to write detailed information about what the solver is doing to the log file. Set this to Live Step Info to get the most detailed reporting.
## Replicate The Crash 
  Now you should try to replicate the crash you had before. 
  When the crash occurs do not try to re-lunch Houdini. Instead send the log file to support and wait for them to provide some information on how to solve your issue.

---

## Profiling
  You can inspect the perfomance of an Axiom simulation uisng the built in profiling tools.
## Profile Tab
  The first thing you need to do is generate some data to profile. You can do this by going to the profile tab on the Axiom solver node.
  You can click Run to generate a file that contains the profile data. It will run the simulation for the specified range and save it to the specified file. 
📌 Be sure to always use the json file extension when naming the file.
  You will see a progress bar while it runs. 
  After the profile has completed you can choose the Open File Profiler option to open the file for inspection.
  Alternatively, you can inspect the live running simulation by choosing the Open Node Profiler option. 
📌 Note that these options enable Debug Verbosity on the solver which may impact performance. When you are done profiling you can disable it by going to the Settings → Solver → Debug Verbosity parameter and setting it to None.
## Profiler 
  You can inspect the various parts of the simulation and see how long individual steps took. You can also see general information about the simulation such as the active voxel count and what device was used.
  You can scrub Houdini’s timeline to see the data for a specific frame. 
  If you want to inspect another file created in a different project or were given one by someone else you can use the Open option at the top of the user interface to open any Axiom profile json file. 
  You can choose to clear the file path with the Clear option which will have the profiler to look for a selected Axiom node to source data from live and interactively. 

---

## How To Upgrade
  This page will go over how to change the version of nodes.
## Installation
  Before chnaging the node versions you need to install the new build the same way you installed the old version.
📌 
    Do not uninstall the old version yet. You need both version installed otherwise you can encounter issues with your existing HIP files. Houdini does not auto convert nodes to newer versions if the old one is missing.
📌 
    We recommend keeping old version installed incase you need to open an old HIP file that has not been converted. They may no longer function in newer Houdini versions but Houdini will always load functional node definitions. This also prevents Houdini from throwing missing definition errors. 
## Updating Node Versions
  First you need to enable the asset definition tool bar in the parameter panel. 
  You do this by going to Assets > Asset Manager
  Then go to configuration and change the Asset Definition Toolbar option to Show Menu Always.
  Now if you go to the parameter panel with a node selected you will see the different versions you can pick from.
  To change the node version just select the version you want.
📌 
    You will need to do for each node in your HIP file. This includes all the source shape and utility nodes.
## Gotchas
### Changed Parameter Names
  Sometimes we need to change parameter names so not all the settings will copy over. You may need to manually copy some parameter values.
### Spare Parameters
  It’s a good idea to also delete all spare parameters after you covert node to remove any old parameters that are left over when you convert.
### Axiom 4.1
  One Axiom 4.1 specific conversion step to be aware of is that by default you may experience a crash when changing from Axiom 4.0 to 4.1. 
  The compute API parameter has new values and when it copies over from the old node it gets set to an invalid value. 
  To fix this set Houdini to manual cook mode before converting.
  Then change the node version.
  Finally go to Advanced > Compute and revert the tab to factory setting by right clicking on the tab itself and choosing the option.
  Now you can re-enable cooking and use the node normally. 
📌 
    It may not be needed but you may want to also do this on the top most output tab.

---

## Changes To Sourcing
  This page will go over how to get the sourcing features you have in Axiom 3 working in Axiom 4.
## Example HIP File
  This HIP file has working examples off all the topics we will cover in this guide.
  [file] axiom4.0_changesToSourcing.hip
## Video
## VDBs
  The naming convention you use in Axiom 3 will still apply to Axiom 4 however there are some major changes to workflows regarding influence fields and new options. 
### Fields
  In Axiom 4 your normal field sources such as density, temperature, fuel, velocity, etc. should just work exactly as you expect. Just name them correctly and plug them in. 
  The default parameter values the solver has for these sources will have it behave just like Axiom 3 with nothing extra needed.
  There are still differences and you can choose to use the new features or not. 
#### Masks
  You can disable or change the mask field on source fields. In Axiom 3 they were always masked by density but now you can change the mask or set it blank to not mask at all. The default is density just like Axiom 3. 
#### Activation
  You can have a source activate new voxels in the areas where they have a non-zero value. In Axiom 3 this was controlled by the activation fields setting in the Advanced → Sparse tab. That still exists and tracks the active state of voxels on the simulation grids as a whole but now you can have sources activate fields in their region separately. This is useful if you need to say source fuel, but not have it activate new voxels. Only add fuel values in voxels that already exist. 
📌 
    Checking a source to be an activator will not mean that the resulting values will be used for tracking the simulation grid’s activation. It just means the immediate area where the source has non-zero values will be active. If you need a field such as temperature or fuel to be tracked you still need to make sure it is enabled in the Advanced → Sparse → Activation Field parameter. 
### Influence
  Influence sources were great because they let you source in an extra velocity field to make custom forces, however they were greatly limiting as well because you could only have 1 of them. 
  Instead, we now have custom fields. These let you source a virtually infinite number of sources all with their own blend modes and settings. 
  If you miss influenceVel and want that same behavior this is how you can set it up to behave the way it did before. 
  Create your vector 3 VDB and name it “influenceVel” just as you would in Axiom 3. 
  Then create your fog or SDF scalar float VDB to define the area of effect and name it “influence” just as you would in Axiom 3.  
  Then under the custom tab add a new entry and set the source name to “influenceVel” and the mask name to “influence”.
  Then choose Velocity to be the field you source into. 
  Now you should get the same behavior as you did in Axiom 3. 
  However, I hope you now see the power of the new workflow. You don't need to name fields specific things. You don't need to use a mask to define the area of effect. You can have more than one of them each with different blend modes. It can be as flexible as you need it to be. 
## Source Shapes
  The biggest change is that you no longer need to source everything if you don’t need to. You can disable fields individually. This allows for more flexibility and you don't need to fight the solver when it tries to source things like color from a source shape when all you wanted is to inject some velocity. 
### Influence
  With this change the influence mode has been removed as it’s now redundant because you have the tools to craft your own influence shapes to meet your needs exactly.
  However, if you want Axiom 3 like influence shapes you need to do 2 things:
#### Activation
  Similar to VDB sources you will find that source shapes have an activation setting. This allows you to have the shape activate voxels in their area of effect. In Axiom 3 this was always on and the influence mode had it disabled. The achieve the same effect in Axiom 4 just disable activation if all you need is to source velocity as a force. Generally a force wouldn’t activate voxels, just affect the ones that already exist. 
#### Sources
  Then turn off everything except velocity. There is nothing stopping you from sourcing density and other fields too in this situation, but to achieve Axiom 3 behavior only leave velocity enabled.
  Then, use the noise, inherit velocity, and force features just as you would in Axiom 3.
#### Custom Source Settings
  You should find this new way of working is more powerful because you can source into selected fields with their own blend modes totally separate from the blend modes and settings on the solver. Like custom field sources you can have a virtually infinite number of these shapes to sculpt your simulation. 

---

## What's New In 4.0
  Here are all the new additions and updates!
## Houdini
  - Supported on the latest production builds of Houdini 20.0, 20.5, and 21.0. 
  - Houdini 19.0 and 19.5 have been dropped from this version of Axiom. 
## UI
  - Reorganized the UI to be less cluttered. Less frequently used parameters have been moved to the advanced tab. 
  - Combustion has been moved to the forces tab.
  - Licensing and profiling have been moved to the advanced tab.
## Core
  - More accurate collisions. Less value loss with animated colliders. Fluid can move through narrow regions more easily.
## Performance
  - Optimized Jacobi kernels for project-non-divergent which makes it 35% faster overall.
  - Intel’s Thread Building Blocks (TBB) is now the default for CPU multi-threaded operations. Even though Axiom primarily uses GPU compute, many operations still run on the CPU related to simulation grid updates and creating output VDBs. Using TBB makes those multi-threaded CPU operations significantly faster on some platforms. It also uses the same TBB version that is used by Houdini. This can be disabled via the AXIOM_THREAD_USE_TBB environment variable.
  - Many small performance optimizations.
  - Solver is anywhere from 5-15% faster overall.
## API & OS Support
  - Cuda is now out of beta.
  - Metal is more stable when doing operations that involve many iterations such as project-non-divergent and diffusion.
  - You can set the AXIOM_COMPUTE_OCL_EXTRA_COMPILER_OPTIONS environment variable to add extra OpenCL compiler options.
## Sourcing
  - Completely re-designed sourcing workflow.
  - You can now choose if a source is masked by another source and choose the mask source by name.
  - Influence sources have been removed. Instead we are introducing custom sources. You can name any input VDB and source it into any field with its own source settings and blending modes. You can add virtually unlimited custom sources via a multi-parm. 
  - Added extra safeguards to make sourcing with NanoVDB safer. Some VDB types not supported by NanoVDB so it will now fall back to sourcing with the CPU.
## Forces
  - Turbulence uses “fast perlin” noise by default now. This is 4-5X faster than traditional perlin noise which is still available in the settings. 
  - Buoyancy now has an ambient temperature parameter and a control ramp added.
  - Fixed an issue with percent based forces. A very high time scale value could cause some field values to be flipped negative if too high. 
  - Aux 1 & Aux 2 fields are now available as a control field for applicable forces.
  - The compute range button on control field ramps no longer needs the field to be output in order to compute the range. It will request the solver compute and return the range of the field on demand. This is much more reliable and can be used when Houdini is in manual mode as well. 
## Output
  - Re-organized output tab that unifies settings per fields rather than per option. 
  - More granular control on a per field level. Previously you could only set masks and volume pruning globally but now they can be set per field. 
  - Fields chosen to be used as a mask don't need to be output for them to have an effect on other output fields. For example you if you don't need to output density but need it as a mask on temperature you don’t need to output density explicitly.
  - You can now output fields and the data structure visualizer at the same time.
## Source Shapes
  - Options to source into specific fields and disable others.
  - Options to have custom source settings per source shape.
  - Similar to VDB sourcing, the influence mode has been removed. You should instead use the source mode and disable the sources that you don't need.
  - You can choose to not have a source shape also activate the region it is in.
  - The pump mode has been re-named to “activate” to better describe its function. It never added anything to the simulation but does activate tiles in its area of effect hence the name change. 
## Nerdy Stuff
  - Most environment variable can now be assigned with a boolean 0 or 1 value to turn features on and off without needing to set and unset them. The environment variable section in the documentation will specify if a variable has this feature if it is marked with the boolean tag.

---

## What's New In 4.1
  Here are all the new additions and updates!
## UI / UX
  - Completely re-worked how the UI is defined on the compiled plug-in. It is now much easier to add new parameters. 
  - Instead of re-setting all parameter each time step the solver only evaluates animated parameters. Static parameters only get set when the parameter is changed by the user. This improves parameter performance. 
  - Replaced control ramps with the same multi parm control ramps found Paradigm.
## Core
  - Added PCG project non divergent. This is slower than Jacobi but is much more accurate. 

---

## Example Projects
  Find a collection of example projects here to get started! All are created with Houdini 21.0 and Axiom 1.1 revisions.
## Simple Explosion
  This project shows how to create a basic explosion.
  ✅ Simulation    ✅ Shading    🚫 Rendering
  simpleExplosion_1.1.hip
## Wind Tunnel
  This project shows how to setup a wind tunnel. Very specific collisions and sinks are needed to make this work.
  ✅ Simulation    🚫 Shading    🚫 Rendering
  windTunnel_1.1.hip
