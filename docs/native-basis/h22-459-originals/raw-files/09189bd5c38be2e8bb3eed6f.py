from builtins import zip
from builtins import range
from typing import Optional, Sequence
import hou
import toolutils
import doptoolutils
import doprbdtoolutils
import objecttoolutils

import crowds

SOLVER_SOURCES_INPUT = 1
SOLVER_STATES_INPUT = 2
SOLVER_TRANSITIONS_INPUT = 3

def populate(agent_objects, source_object, default_state = ""):
    root = hou.node("/obj")

    # Check for existing setup created by this tool.
    merge_sop = None
    crowdsource_object = None
    for n in root.allSubChildren():
        if n.type().name() == "crowdsource::3.0" and n.type().category().name() == "Sop":
            crowdsource_object = n.parent()
            merge_sop = hou.node(crowdsource_object.path() + "/merge_crowdsources")
            break

    if not crowdsource_object:
        crowdsource_object = root.createNode("geo", "crowdsource")
        objecttoolutils.initEmptyGeometryObject(crowdsource_object)
        crowdsource_object.moveToGoodPosition()

    initnodes = set(crowdsource_object.children())

    if merge_sop is None:
        merge_sop = crowdsource_object.createNode("merge", "merge_crowdsources")
        out_sop = crowdsource_object.createNode("null", "OUT")
        out_sop.setNextInput(merge_sop)
        out_sop.setDisplayFlag(1)
        out_sop.setRenderFlag(1)

    crowdsource_sop = crowdsource_object.createNode("crowdsource::3.0", "crowdsource")
    crowdsource_sop.parm("scatteragent").set(1000)
    crowdsource_sop.parm("sizex").set(100)
    crowdsource_sop.parm("sizey").set(50)
    crowdsource_sop.parm("state").set(default_state)

    if len(agent_objects) > 1:
        crowdsource_sop.parm("randomizeagent").set(True)

    # Fetch agent primitives.
    if agent_objects:
        agentmerge_sop = crowdsource_object.createNode(
                "object_merge", "source_agents")
        crowdsource_sop.setInput(0, agentmerge_sop)

        agentmerge_sop.parm("numobj").set(len(agent_objects))
        agentmerge_sop.parm("xformpath").set(".")

        for idx, agent_object in enumerate(agent_objects, start = 1):
            agent_object.setDisplayFlag(False)
            agentmerge_sop.parm("objpath{0}".format(idx)).set(
                    agent_object.displayNode().path())

    # Add constraint network.
    agentconstraintnetwork_sop = crowdsource_object.createNode("agentconstraintnetwork")
    agentconstraintnetwork_sop.setNextInput(crowdsource_sop)

    out_constraints_sop = hou.node(crowdsource_object.path() + "/OUT_constraints")
    if not out_constraints_sop:
        out_constraints_sop = crowdsource_object.createNode("merge", "OUT_constraints")

    out_constraints_sop.setNextInput(agentconstraintnetwork_sop,1)
    merge_sop.setNextInput(agentconstraintnetwork_sop)

    # Merge in terrain geometry.
    if source_object:
        crowdsource_input_sop = crowdsource_object.createNode("object_merge", source_object.name() + "_input")
        crowdsource_sop.setInput(1, crowdsource_input_sop)
        crowdsource_sop.parm("scatteragent").set(20)
        crowdsource_sop.parm("sizex").set(10)
        crowdsource_sop.parm("sizey").set(10)
        crowdsource_input_sop.parm("objpath1").set(source_object.displayNode().path())
        crowdsource_input_sop.parm("xformpath").set(".")

    # Layout new nodes.
    finalnodes = set(crowdsource_object.children())
    newnodes = list(finalnodes - initnodes)
    toolutils.moveNodesToGoodPosition(newnodes)
    crowdsource_object.layoutChildren(newnodes)

    crowdsource_sop.setCurrent(True, True)
    return crowdsource_object

def populateInteractive(kwargs):
    scene_viewer = toolutils.sceneViewer()

    # Ask for agent
    agent_objects = scene_viewer.selectObjects(
        prompt = "Select agent setup object, if any, then press Enter to complete.",
        allowed_types = ("geo",))

    # Ask for source points if any
    source_objects = scene_viewer.selectObjects(
        prompt = "Now select terrain/points object for crowd placement, if any, then press Enter to complete.",
        use_existing_selection = False,
        allow_multisel = False,
        allowed_types = ("geo",))
    source_object = source_objects[0] if source_objects else None

    # Check if agent object contains agents.
    for agent_object in agent_objects:
        sopnode = agent_object.displayNode()
        geo = sopnode.geometry() if sopnode else None
        has_agents = geo and geo.containsPrimType(hou.primType.Agent)

        if not has_agents:
            raise hou.Error("Geometry does not contain agent primitives.")

    populate(agent_objects, source_object)


def chooseStatesToCreate(source_geo, dopnet):
    # Prompt the user to select which states they want to create, based on the
    # available animation clips. The default is to create a state for each
    # value of the 'state' point attribute.
    agent_defns = findAgentDefinitions(source_geo)
    states_to_create = []

    if agent_defns:
        clip_names = set()
        for defn in agent_defns:
            clip_names.update([c.name() for c in defn.clips()])

        state_attrib = source_geo.findPointAttrib("state")
        current_states = set()
        if state_attrib:
            current_states = set(state_attrib.strings())

        # If there is an existing simulation, remove choices for states that
        # were already created.
        created_states = set()
        if dopnet:
            (_, created_state_names) = findStates(dopnet)
            created_states = set(created_state_names)

        state_names = list(
                clip_names.union(current_states).difference(created_states))
        state_names.sort()
        state_names.append("ragdoll")

        if len(state_names) > 0:
            initial_selection = [idx for (idx, state) in enumerate(state_names)
                                 if state in current_states]

            selection = hou.ui.selectFromList(
                    state_names, default_choices = initial_selection,
                    message = "Select states to add to the crowd simulation.",
                    title = "States")
            states_to_create = [state_names[idx] for idx in selection]
        else:
            states_to_create = state_names

    return states_to_create

def simulate(source_object):
    """ Sets up a crowd simulation for the agents in source_object.
        Returns the merge nodes for states and transitions.
    """
    source_sop = source_object.displayNode()

    # Set up constraint network geometry if needed.
    constraints_node = hou.node(source_object.path() + "/OUT_constraints")
    if not constraints_node:
        constraints_setup = source_object.createNode("agentconstraintnetwork")
        constraints_setup.setNextInput(source_sop)
        constraints_setup.moveToGoodPosition()

        source_sop = source_object.createNode("null", "OUT")
        source_sop.setNextInput(constraints_setup)
        source_sop.moveToGoodPosition()

        constraints_node = source_object.createNode("null", "OUT_constraints")
        constraints_node.setNextInput(constraints_setup, 1)
        constraints_node.moveToGoodPosition()

    dopnet = doptoolutils.createNewDopNetwork(
            name = "crowd_sim", init_dopnet = False)

    crowdsolver = dopnet.createNode("crowdsolver::3.0", "crowdsolver")
    crowdobject = dopnet.createNode("crowdobject", "crowdobject")
    multisolver = dopnet.createNode("multisolver", "multisolver")
    staticsolver = dopnet.createNode("staticsolver", "staticsolver")

    bulletsolver = dopnet.createNode("bulletrbdsolver", "bulletrbdsolver")
    bulletsolver.parm("constraintsolvertype").set("gaussseidelisland")
    bulletsolver.parm("randomize_order").set(True)

    gravity = dopnet.createNode("gravity", "gravity")

    crowdsource = dopnet.createNode("popsource::2.0", source_object.name())
    crowdsource.parm("emittype").set("allgeo")
    crowdsource.parm("showguide").set(False)
    crowdsource.parm("soppath").set(source_sop.path())
    crowdsource.parm("impulseactiveate").setExpression("$SF==1")
    crowdsource.parm("jitterbirthtime").set("none")

    merge_states = dopnet.createNode("merge", "merge_states")
    merge_transitions = dopnet.createNode("merge", "merge_transitions")
    merge_active_collisions = dopnet.createNode("merge", "merge_active_collisions")
    merge_static_collisions = dopnet.createNode("merge", "merge_static_collisions")
    merge_static_solver = dopnet.createNode("merge", "merge_static_solver")

    output_dop = dopnet.displayNode()

    crowdsolver.setInput(SOLVER_SOURCES_INPUT, crowdsource)
    crowdsolver.setInput(SOLVER_STATES_INPUT, merge_states)
    crowdsolver.setInput(SOLVER_TRANSITIONS_INPUT, merge_transitions)
    multisolver.setNextInput(merge_active_collisions)
    multisolver.setNextInput(crowdsolver)
    multisolver.setNextInput(bulletsolver)
    merge_active_collisions.setNextInput(crowdobject)
    staticsolver.setNextInput(merge_static_collisions)
    merge_static_solver.setNextInput(staticsolver)
    merge_static_solver.setNextInput(multisolver)
    gravity.setNextInput(merge_static_solver)
    output_dop.setNextInput(gravity)

    # Add constraint network.
    doprbdtoolutils.createRagdollConstraintNetwork(dopnet, crowdobject,
                                                   constraints_node)

    dopnet.layoutChildren()

    # Create crowd_sim_import in the source object.
    (sim_import, _) = doptoolutils.createDopIO(source_object,
                                               "crowd_sim_import",
                                               "crowd_sim_cache")
    sim_import.parm("doppath").set(dopnet.path())
    sim_import.parm("dopnode").set(crowdobject.path())
    sim_import.parm("fields").set(1)
    sim_import.parm("visible1").set("nochange")
    sim_import.parm("objname1").set("crowdobject")
    sim_import.parm("fieldname1").set("Geometry")

    dopnet.setCurrent(True, True)

    return (merge_states, merge_transitions)

def simulateInteractive(kwargs):
    """ Create crowd dop sim based on user input or default setup if none
    """

    if toolutils.placeToolImmediately(kwargs):
        # Create default setup.
        root = hou.node('/obj')
        agentname = "mocapbiped1"

        # Write out the agent definition.
        rest_cycle = root.createNode(agentname, 'rest_cycle')
        rest_cycle.parm("animation").set("rest")

        stand_cycle = root.createNode(agentname, 'stand_cycle')
        stand_cycle.parm("animation").set("standing")
        stand_cycle.parm("inplaceanim").set(0)

        walk_cycle = root.createNode(agentname, 'walk_cycle')

        toolutils.moveNodesToGoodPosition(
            [rest_cycle, stand_cycle, walk_cycle])

        input_type = "scene"
        agent_object = bakeAgent(input_type, rest_cycle, None, agentname, 'rest')
        addClip(agent_object, input_type, stand_cycle, 'stand')
        addClip(agent_object, input_type, walk_cycle, 'walk')

        # Set up collision geometry and joint limits for ragdolls.
        out_node = agent_object.displayNode()

        collisionlayer = agent_object.createNode('agentcollisionlayer::2.0',
                                                 'build_collision_layer')
        toolutils.connectMultiInputsAndOutputs(collisionlayer, False, [],
                                               [(out_node, 0)])
        applyPresetForKnownAgents(collisionlayer, agentname)
        collisionlayer.moveToGoodPosition()

        joint_limits = agent_object.createNode('agentconfigurejoints::2.0',
                                               'joint_limits')
        toolutils.connectMultiInputsAndOutputs(joint_limits, False, [],
                                               [(out_node, 0)])
        applyPresetForKnownAgents(joint_limits, agentname)
        joint_limits.moveToGoodPosition()

        # Populate the crowd.
        crowdsource_object = populate([agent_object], None, default_state = "stand")

        # Set up the DOP sim.
        (merge_states, merge_transitions) = simulate(crowdsource_object)
        dopnet = merge_states.parent()

        # Create states and transitions.
        walk_state = dopnet.createNode("crowdstate::3.0", "walk")
        walk_state.parm("randomclipoffset").set(1.5)
        walk_state.parm("gaitspeed").set(1.25)

        wander = dopnet.createNode("popsteerwander", "wander")
        wander.parm("forcez").set(10)
        wander.parm("amp").set(3)
        wander.parm("output").set(0)
        wander.parm("type").set(1)

        stand_state = dopnet.createNode("crowdstate::3.0", "stand")
        stand_state.parm("randomclipoffset").set(1)
        stand_state.parm("gaitspeed").set(0)

        ragdoll_state = dopnet.createNode("crowdstate::3.0", "ragdoll")
        ragdoll_state.parm("rbdragdoll").set("active")

        trigger = dopnet.createNode("crowdtrigger::2.0", "trigger_stateduration")
        trigger.parm("type").set(10)
        trigger.parm("triggername").set("stateduration")
        trigger.parm("statedurationcondition").set(2)
        trigger.parm("stateduration").set(0.0416667)

        transition = dopnet.createNode("crowdtransition::3.0", "transition_stand_walk")
        transition.parm("instate").set("stand")
        transition.parm("outstate").set("walk")
        transition.parm("duration").set(0.25)
        transition.parm("randomstart").set(True)
        transition.parm("randomstartoffset").set(3)

        transition.setNextInput(trigger)
        merge_transitions.setNextInput(transition)
        wander.setNextInput(walk_state)
        merge_states.setNextInput(wander)
        merge_states.setNextInput(stand_state)
        merge_states.setNextInput(ragdoll_state)

        dopnet.layoutChildren()

    else:
        scene_viewer = toolutils.sceneViewer()

        # Ask for source geometry.
        source_objects = list(scene_viewer.selectObjects(
            prompt = "Select crowdsource object and press Enter",
            use_existing_selection = True,
            allow_multisel = False,
            allowed_types = ("geo",)))

        if not source_objects:
            raise hou.Error("Nothing was selected.")
        crowdsource_object = source_objects[0]

        source_sop = crowdsource_object.displayNode()
        source_geo = source_sop.geometry() if source_sop else None

        if not (source_geo and source_geo.containsPrimType(hou.primType.Agent)):
            raise hou.Error("Geometry does not contain agent primitives.")

        existing_dopio = toolutils.findInputNodeOfBaseType(
                source_sop, "dopimportfield", includeme = True)
        dopnet = None
        if existing_dopio:
            # Find the existing crowd simulation and ask the user what they
            # want to do with it.
            dopnet = hou.node(existing_dopio.evalParm("doppath"))

            choice = hou.ui.displayMessage(
                    "Agents are already simulated. Create a new simulation?",
                    buttons = ("Yes", "No", "Cancel"),
                    close_choice = 2)
            if choice == 0:
                dopnet = None
            elif choice == 2:
                return
        else:
            # Ensure that the agents have a state attribute.
            if not source_geo.findPointAttrib("state"):
                wrangle = crowdsource_object.createNode("attribwrangle", "set_state")
                wrangle.parm("snippet").set("s@state = agentclipnames(0, @primnum)[0];")
                wrangle.setNextInput(source_sop)
                wrangle.setDisplayFlag(True)
                wrangle.setRenderFlag(True)
                wrangle.moveToGoodPosition()

                source_sop = wrangle
                source_geo = wrangle.geometry()

        states_to_create = chooseStatesToCreate(source_geo, dopnet)

        # Set up the DOP network.
        if not dopnet:
            (merge_states, merge_transitions) = simulate(crowdsource_object)
            dopnet = merge_states.parent()
        else:
            crowdsolver = findCrowdSolver(dopnet)
            merge_states = toolutils.findInputNodeOfType(
                    crowdsolver.inputs()[SOLVER_STATES_INPUT], 'merge',
                    includeme = True)

            if not merge_states:
                raise hou.Error("Missing merge node.")

        # Create the states.
        for state in states_to_create:
            state_node = dopnet.createNode("crowdstate::3.0", state)

            if state == "ragdoll":
                state_node.parm("rbdragdoll").set("active")

            merge_states.setNextInput(state_node)

        dopnet.layoutChildren()

def selectSOPGeometry(prompt, allow_multisel = False, allowed_types = ("geo",)):
    """ Prompts the user for a geometry object selection, and verifies that the
        objects are non-empty. Returns the list of selected objects (if
        allow_multisel is True), or the single selected object otherwise.
    """
    scene_viewer = toolutils.sceneViewer()

    # Ask for source if any
    source_objects = list(scene_viewer.selectObjects(prompt,
        use_existing_selection = True,
        allow_multisel = allow_multisel,
        allowed_types = allowed_types))

    if len(source_objects) == 0:
        raise hou.Error("Nothing was selected.")

    for obj in source_objects:
        if not obj.displayNode():
            raise hou.Error("Selected object has no SOPs.")

    return source_objects if allow_multisel else source_objects[0]

def selectState(dopnet, message):
    """ Prompts the user to select one of the states in the crowd simulation
        (or all states). Returns the crowd state DOP, or None if all states
        were selected.
    """
    (state_nodes, state_names) = findStates(dopnet)
    state_nodes = [None] + state_nodes
    state_names = ["All States"] + state_names

    selection = hou.ui.selectFromList(
            state_names, exclusive = True, message = message,
            title = "Select State")

    return state_nodes[selection[0]]

def findCrowdSim():
    dopnet = hou.currentDopNet()
    output_dop = dopnet.displayNode() if dopnet else None
    if not dopnet or not output_dop:
        raise hou.Error("Missing crowd sim DOP network.")

    return dopnet

def findCrowdSolver(dopnet):
    crowdsolver = doptoolutils.findSolverInInput(
            dopnet.displayNode(), "crowdsolver")

    if not crowdsolver:
        raise hou.Error("Missing crowd solver.")

    return crowdsolver

def findStates(dopnet):
    """ Returns a list of the crowd state nodes and state names."""
    state_nodes = []
    state_names = []

    for node in dopnet.children():
        # Instead of checking the type name, look for a state name parameter so
        # that custom crowd state nodes can be supported.
        statename_parm = node.parm("statename")
        if statename_parm:
            state_nodes.append(node)
            state_names.append(statename_parm.evalAsString())

    return (state_nodes, state_names)

def wireNodeInState(node, state_node, crowdsolver):
    """ Wire the given node into the state's stream. If state_node is None, the
        node is wired just before the crowd solver's state input, so it will
        apply to all states.
    """
    if state_node:
        toolutils.connectMultiInputsAndOutputs(
                node, False, [(state_node, 0)], [])
    else:
        toolutils.connectMultiInputsAndOutputs(
                node, False, [], [(crowdsolver, SOLVER_STATES_INPUT)])

    node.moveToGoodPosition()

def addterrain(kwargs):
    """ Add terrain object to the crowd simulation.
    """
    terrain_object = selectSOPGeometry(
            "Select terrain object and press Enter to complete.")
    dopnet = findCrowdSim()
    crowdsolver = findCrowdSolver(dopnet)

    crowdsolver.parm("terrainprojection").set(True)
    crowdsolver.parm("terrainsoppath").set(terrain_object.displayNode().path())

    # Create the static solver (if necessary) and the terrain DOP object.
    terrain_object = doptoolutils.genericConvertToDopObject(
            terrain_object, "terrainobject", terrain_object.name())
    terrain_object.setCurrent(True, True)

def addobstacle(kwargs):
    """ Add obstacle object to the crowd simulation.
    """
    obstacle_objects = selectSOPGeometry(
            "Select obstacle objects and press Enter to complete.",
            allow_multisel = True)
    dopnet = findCrowdSim()
    crowdsolver = findCrowdSolver(dopnet)

    for obstacle_object in obstacle_objects:
        obstacle_dop = dopnet.createNode(
                "popsteerobstacle::2.0", "obstacle_" + obstacle_object.name())
        obstacle_dop.parm("output").set(0)
        obstacle_dop.parm("weight").set(1)
        obstacle_dop.parm("fovsamples").set(128)
        obstacle_dop.parm("bindgeoinput2").set(
                obstacle_object.displayNode().path())

        wireNodeInState(obstacle_dop, None, crowdsolver)
        obstacle_dop.setCurrent(True, True)


def addClip(agent_obj,
            input_type,
            subnet,
            clipname,
            filepath=None,
            lopnode=None):
    clip_sop = toolutils.findInputNodeOfType(agent_obj.displayNode(),
                                             "agentclip::2.0")
    if not clip_sop:
        clip_sop = agent_obj.createNode("agentclip", "load_clips")
        clip_sop.setNextInput(agent_obj.displayNode())
        clip_sop.moveToGoodPosition()
        clip_sop.setDisplayFlag(True)
        clip_sop.setRenderFlag(True)
        clip_sop.parm("clips").set(0)

    # Agent Clip SOP uses 'subnet' instead of 'scene' for the input menu, but
    # matches otherwise.
    clip_input_type = "subnet" if input_type == "scene" else input_type

    clip_idx = clip_sop.parm("clips").eval() + 1
    clip_sop.parm("clips").set(clip_idx)
    clip_sop.parm("source{0}".format(clip_idx)).set(clip_input_type)
    clip_sop.parm("name{0}".format(clip_idx)).set(clipname)

    if input_type == "scene":
        clip_sop.parm("objsubnet{0}".format(clip_idx)).set(subnet.path())

    elif input_type == "fbx":
        clip_sop.parm("file{0}".format(clip_idx)).set(filepath)

    elif input_type == "usd":
        if lopnode:
            clip_sop.parm("loppath{0}".format(clip_idx)).set(
                clip_sop.relativePathTo(lopnode))
        else:
            clip_sop.parm("usdsource{0}".format(clip_idx)).set("file")
            clip_sop.parm("usdfile{0}".format(clip_idx)).set(filepath)

    # TODO - add support in the Agent Clip SOP for previewing the last added
    # clip, like the Agent SOP, since we don't know the FBX clip names ahead of
    # time.
    if input_type != "fbx":
        clip_sop.parm("setcurrentclip").set(True)
        clip_sop.parm("currentclip").set(clipname)

    if subnet:
        subnet.setDisplayFlag(False)

    return clip_sop


def bakeAgent(input_type,
              subnet,
              filepath,
              agentname,
              clipname,
              lopnode=None):
    root = hou.node("/obj")
    agent_obj_name = agentname + "_setup"
    agent_obj = root.node(agent_obj_name)

    if agent_obj:
        raise hou.Error("Agent '{0}' already exists.".format(agentname))

    agent_obj = root.createNode("geo", agent_obj_name)
    objecttoolutils.initEmptyGeometryObject(agent_obj)
    agent_obj.moveToGoodPosition()

    agent_sop = agent_obj.createNode("agent", "create_agent")
    agent_sop.parm("agentname").set(agentname)
    agent_sop.parm("input").set(input_type)
    if input_type == "scene":
        agent_sop.parm("clipname").set("rest")
        agent_sop.parm("objsubnet").set(subnet.path())
        agent_sop.parm("rangemode").set("specific")
        agent_sop.parm("f2").setExpression("$FSTART")

    elif input_type == "fbx":
        agent_sop.parm("fbxclipname").set(clipname)
        agent_sop.parm("input").set("fbx")
        agent_sop.parm("fbxfile").set(filepath)

    elif input_type == "usd":
        if lopnode:
            agent_sop.parm("loppath").set(agent_sop.relativePathTo(lopnode))
        else:
            agent_sop.parm("usdsource").set("file")
            agent_sop.parm("usdfile").set(filepath)

    agentclip_sop = addClip(agent_obj, input_type, subnet, clipname, filepath,
                            lopnode)

    agent_defn = agent_obj.createNode("null", "AGENT_DEFINITION")
    agent_defn.setNextInput(agentclip_sop)

    agent_cache_sop = agent_obj.createNode("agentdefinitioncache",
                                           "cache_to_disk")
    agent_cache_sop.parm("agentname").set(agent_sop.parm("agentname"))
    agent_cache_sop.setNextInput(agent_defn)

    agent_prep = agent_obj.createNode("agentprep", "agentprep")
    agent_prep.parm("agentname").set(agent_sop.parm("agentname"))
    agent_prep.parm("cachedir").set(agent_cache_sop.parm("cachedir"))
    agent_prep.setNextInput(agent_cache_sop)
    applyPresetForKnownAgents(agent_prep, agentname)

    out_sop = agent_obj.createNode("null", "OUT")
    out_sop.setNextInput(agent_prep)
    out_sop.setDisplayFlag(True)
    out_sop.setRenderFlag(True)

    agent_obj.layoutChildren()
    agentclip_sop.setCurrent(True, True)

    return agent_obj


def _agentInputType(source_type):
    input_type = None
    if source_type == crowds.BakeAgentDialog.SOURCE_FBX:
        input_type = "fbx"
    elif source_type in (crowds.BakeAgentDialog.SOURCE_USD,
                         crowds.BakeAgentDialog.SOURCE_LOP):
        input_type = "usd"
    else:
        input_type = "scene"

    return input_type


def bakeAgentInteractive(kwargs):
    # Check for an initial object selection.
    selected_objects = [
        node for node in hou.selectedNodes()
        if node.type().category() == hou.objNodeTypeCategory()
    ]
    selection = selected_objects[0] if selected_objects else None

    dialog = crowds.BakeAgentDialog("Agent", selected_object=selection)
    if not dialog.exec():
        return

    agentname = dialog.agentName()
    subnet = dialog.subnet()
    filepath = dialog.filePath()
    clipname = dialog.clipName()
    lopnode = dialog.lopNode()

    bakeAgent(
        _agentInputType(dialog.sourceType()), subnet, filepath, agentname,
        clipname, lopnode)


def addClipInteractive(kwargs):
    # Ask for agent.
    scene_viewer = toolutils.sceneViewer()
    selection = scene_viewer.selectGeometry(
        prompt='Select agent to add a clip to and press Enter to complete.',
        primitive_types=[hou.primType.Agent],
        allow_obj_sel=True)
    if not selection.nodes():
        raise hou.Error("No agent was selected.")
    agent_obj = selection.nodes()[0].parent()

    dialog = crowds.BakeAgentDialog("Add Clip", enable_agentname=False)
    if not dialog.exec():
        return

    subnet = dialog.subnet()
    filepath = dialog.filePath()
    clipname = dialog.clipName()

    agentclip_sop = addClip(
        agent_obj,
        _agentInputType(dialog.sourceType()),
        subnet,
        clipname,
        filepath,
        lopnode=dialog.lopNode())
    agentclip_sop.setCurrent(True, True)


def crowdpath(kwargs):
    """ Ask user for curve object and add it as path to the crowd sim.
    """
    source_object = selectSOPGeometry(
        "Select curve object to be used as a path and press Enter to complete.")
    dopnet = findCrowdSim()
    crowdsolver = findCrowdSolver(dopnet)

    state_node = selectState(dopnet,
            "Select the state in which agents should follow the path.")

    path_dop = dopnet.createNode("popsteerpath", "path_" + source_object.name())
    path_dop.parm("output").set(0)
    path_dop.parm("soppath").set(source_object.displayNode().path())

    wireNodeInState(path_dop, state_node, crowdsolver)
    path_dop.setCurrent(True, True)

def crowdlookat(kwargs):
    """ Ask user for lookat object and which state to add it to the crowd sim
    """
    target = selectSOPGeometry(
        "Select the look at target object and press Enter to complete.",
        allowed_types=("*", ))
    dopnet = findCrowdSim()
    crowdsolver = findCrowdSolver(dopnet)

    state_node = selectState(
        dopnet,
        "Select the state in which agents should look at the target object.")

    lookat_dop = dopnet.createNode("agentlookat", "lookat_" + target.name())
    lookat_dop.parm("targettype").set("object")
    lookat_dop.parm("objectpath").set(target.path())

    # Wire in the node and enable lookats on the solver.
    wireNodeInState(lookat_dop, state_node, crowdsolver)
    crowdsolver.parm("lookat").set(True)

    lookat_dop.setCurrent(True, True)


def crowdpaintdensity(kwargs):
    """ Create setup to paint density for crowdsource
    """

    # ask for crowdsource object
    scene_viewer = toolutils.sceneViewer()
    source_object = list(scene_viewer.selectObjects(
            prompt = "Select crowdsource object to paint density for then press Enter to continue",
            use_existing_selection=True,
            allow_multisel = False,
            allowed_types = ("geo",)))

    if len(source_object)==0:
        raise hou.Error("Nothing selected.")

    scene_viewer.setPwd(source_object[0])

    # get possible crowdsources
    nodelist = source_object[0].children()
    crowdsourcelist = []
    for n in nodelist:
        if n.type().nameComponents()[2] == "crowdsource" and len(n.inputConnectors()[1]) == 1:
            if n.inputConnectors()[1][0].inputNode().geometry().iterPrims():
                crowdsourcelist.append(n)

    if not crowdsourcelist:
        raise hou.Error("Missing crowdsource node with geometry input.")

    # prompt user to select from valid sources (have inputs that contains prim geometry); if found only one node use it without dialog promot
    crowdsourceSelected = None
    if len(crowdsourcelist) > 1:
        nodepaths = [single_node.path() for single_node in crowdsourcelist]
        choice_tuple = hou.ui.selectFromList(nodepaths, exclusive=True, message="Choose crowdsource to paint density", title="Crowdsources")
        if choice_tuple:
            assert len(choice_tuple) <= 1
            choice = choice_tuple[0]
            crowdsourceSelected = hou.node(nodepaths[choice])
    elif len(crowdsourcelist) == 1:
        crowdsourceSelected = crowdsourcelist[0]

    if not crowdsourceSelected:
        raise hou.Error("No crowdsource node was selected.")

    # check if attribcreate exists in chain
    attribcreate_node = toolutils.findInputNodeOfTypeWithParms(crowdsourceSelected, 'attribcreate::2.0',  {'name1': 'density'}, True)
    if (attribcreate_node is None):
        attribcreate_node = crowdsourceSelected.parent().createNode("attribcreate::2.0","attribcreate_density")
        attribcreate_node.parm("name1").set("density")
        attribcreate_node.setNextInput(crowdsourceSelected.inputs()[1])
        crowdsourceSelected.setInput(1,attribcreate_node,0)
        attribcreate_node.moveToGoodPosition()

    # add paint node; if one exists wire it as next
    paint_node = crowdsourceSelected.parent().createNode("paint","paint_density")
    paint_node.parm("overridecd").set(1)
    paint_node.parm("cdname").set("density")
    paint_node.setNextInput(crowdsourceSelected.inputs()[1])
    crowdsourceSelected.setInput(1,paint_node,0)
    paint_node.moveToGoodPosition()

    # set paint current
    paint_node.setCurrent(True, True)
    scene_viewer.enterCurrentNodeState()

def addcollisionlayer(kwargs):
    """ Add a collision layer to an agent.
    """
    sceneviewer = toolutils.activePane(kwargs)

    if isinstance(sceneviewer, hou.SceneViewer):
        selection = sceneviewer.selectGeometry(
            prompt = 'Select agent to add a collision layer to and press Enter to complete.',
            primitive_types = [hou.primType.PackedPrim],
            allow_obj_sel = False)

        if not selection.nodes():
            raise hou.Error("No agents were selected.")

        selection.setGeometryType(hou.geometryType.Points)
        parent = selection.nodes()[0].parent()
        sopnode = selection.mergedNode(parent, hou.shelves.runningTool().name())
        out_node = hou.node(parent.path() + "/OUT")
        input_node = out_node.inputs()[0] if out_node else sopnode

        collisionlayer = parent.createNode('agentcollisionlayer::2.0',
                                           'build_collision_layer')
        collisionlayer.parm('agentgroup').set(selection.mergedSelectionString())
        collisionlayer.setInput(0, input_node, 0)
        collisionlayer.moveToGoodPosition()
        collisionlayer.setDisplayFlag(True)
        collisionlayer.setRenderFlag(True)
        collisionlayer.setCurrent(True, True)

        agentname = findInputAgentName(collisionlayer, group_parm_name="agentgroup")
        applyPresetForKnownAgents(collisionlayer, agentname)

        if out_node:
            out_node.setInput(0, collisionlayer, 0)
            out_node.moveToGoodPosition()

        sceneviewer.enterCurrentNodeState()

def configurejoints(kwargs):
    """ Add an Agent Configure Joints node and a test simulation.
    """
    sceneviewer = toolutils.activePane(kwargs)

    if isinstance(sceneviewer, hou.SceneViewer):
        selection = sceneviewer.selectGeometry(
            prompt = 'Select agent whose joints to configure and press Enter to complete.',
            primitive_types = [hou.primType.PackedPrim],
            allow_obj_sel = False)

        if not selection.nodes():
            raise hou.Error("No agents were selected.")

        selection.setGeometryType(hou.geometryType.Points)
        parent = selection.nodes()[0].parent()
        sopnode = selection.mergedNode(parent, hou.shelves.runningTool().name())
        out_node = hou.node(parent.path() + "/OUT")
        input_node = out_node.inputs()[0] if out_node else sopnode

        joints = parent.createNode("agentconfigurejoints::2.0",
                                   "configure_joints")
        joints.parm('agentgroup').set(selection.mergedSelectionString())
        joints.setInput(0, input_node, 0)
        joints.moveToGoodPosition()
        joints.setDisplayFlag(True)
        joints.setRenderFlag(True)
        joints.setCurrent(True, True)

        # Apply the preset if this built-in character. Otherwise, use the
        # collision layer and animation clips to add initial rotation limits.
        agentname = findInputAgentName(joints, group_parm_name="agentgroup")
        if not applyPresetForKnownAgents(joints, agentname):
            joints.parm('filterbycollisionlayer').set(True)
            joints.parm('computelimits').set(True)

        if out_node:
            out_node.setInput(0, joints, 0)
            out_node.moveToGoodPosition()

        # Set up a simulation for testing the ragdoll.
        sim = parent.createNode('testsim_ragdoll', 'TEST_RAGDOLL_SIM')
        sim.setInput(0, joints)
        sim.moveToGoodPosition()

        sceneviewer.enterCurrentNodeState()

def crowdtargetposition(kwargs):
    """ Add a target position steering force that agents will try to reach
    """
    dopnet = findCrowdSim()
    crowdsolver = findCrowdSolver(dopnet)
    state_node = selectState(dopnet, "Select the state in which agents should move towards a target position.")

    popsteerseek = dopnet.createNode("popsteerseek", "target_position")
    popsteerseek.parm("output").set(0)
    popsteerseek.parm("goalz").set(50)

    wireNodeInState(popsteerseek, state_node, crowdsolver)
    popsteerseek.setCurrent(True, True)

def crowdagentcam(kwargs):
    """ Create cameras attached to the agent transforms
    """
    scene_viewer = toolutils.sceneViewer()
    selection = scene_viewer.selectGeometry(
                    prompt="Select agent or multiple agents to attach cameras to, then press Enter to complete",
                    primitive_types = [hou.primType.Agent],
                    allow_obj_sel = False)

    if not selection.nodes():
        raise hou.Error("No agents were selected.")

    agentlist = list(selection.selectionStrings()[0].strip().split(" "))

    # Create agent cam node
    agentcam_node = hou.node('/obj').createNode("agentcam","AgentCam")
    agentcam_node.parm("agentsource").set(selection.nodes()[0].parent().path())
    agentcam_node.parm("cameras").set(len(agentlist))
    agentcam_node.parm("cameras").pressButton()
    for i, selection in enumerate(agentlist):
        agentcam_node.parm("agentid"+str(i+1)).set(selection)

    agentcam_node.moveToGoodPosition()
    scene_viewer.setPwd(hou.node('/obj'))
    toolutils.homeToSelectionNetworkEditorsFor(agentcam_node)
    agentcam_node.setSelected(True, clear_all_selected=True)
    agentcam_node.setCurrent(True, True)


def applyPresetForKnownAgents(node, agentname):
    """
    Applies presets for built-in characters such as mocapbiped1, if the node
    has a legacy preset or recipe node preset with that name.
    """
    if not agentname:
        return False

    # First attempt to apply a legacy preset.
    preset_cmd = f"oppresetload {node.path()} {agentname}"

    (cmd_output, cmd_errors) = hou.hscript(preset_cmd)
    if not cmd_errors:
        # print(f"{agentname}: applied legacy preset for {node.type()}")
        return True

    # Otherwise, find a recipe node preset for the agent.
    import recipeutils
    recipes = recipeutils.dataFromRecipes(
        recipeutils.RecipeCategory.nodePreset,
        nodetype_patterns=node.type().nameWithCategory())

    for recipe in recipes:
        recipe_name = recipe["name"]
        recipe_type = hou.nodeType(hou.dataNodeTypeCategory(), recipe_name)
        if not recipe_type:
            continue

        _, _, preset_name, _ = recipe_type.nameComponents()

        if preset_name == agentname:
            hou.data.applyNodePresetRecipe(recipe_name, node)
            # print(f"{agentname}: applied recipe preset {recipe_name}")
            return True

    # print(f"{agentname}: no preset exists for {node.type()}")
    return False


def findInputAgentName(node, input_index=0, group_parm_name="group"):
    """
    Finds the 'agentname' for the agent primitive from the node's input
    geometry, or returns the empty string.
    """
    agent = findInputAgent(node, input_index, group_parm_name)
    if not agent:
        return ""

    geo = agent.geometry()
    agentname_attrib = geo.findPointAttrib("agentname")
    if not agentname_attrib:
        return ""

    agentname = agent.points()[0].attribValue(agentname_attrib)
    return agentname


def findInputAgent(node, input_index=0, group_parm_name="group"):
    """ Finds the agent primitive from the node's input geometry, or returns
        None.
    """
    if not node.inputs():
        return None

    geo = node.inputGeometry(input_index)

    # Use the input group if specified.
    group_parm = node.parm(group_parm_name)
    group_str = group_parm.evalAsString() if group_parm else ""

    return findAgent(geo, group_str)


def findInputAgentDefinitions(node, frame=None, input_index=0, group_str=None,
                              group_type=hou.geometryType.Primitives):
    """ Finds the unique agent definitions from the node's input geometry."""
    if not node.inputs():
        return []

    if frame is not None:
        geo = node.inputGeometryAtFrame(frame, input_index)
    else:
        geo = node.inputGeometry(input_index)

    if not geo:
        return []

    # Use the input group if specified.
    if group_str is None:
        group_parm = node.parm('group')
        group_str = group_parm.evalAsString() if group_parm else ""

    return findAgentDefinitions(geo, group_str=group_str, group_type=group_type)


def _buildMotionPathAgentGroup(node: hou.SopNode) -> tuple[Optional[hou.Geometry], str]:
    """
    Returns the crowd geometry and agent primitive group that correspond to
    the SOP's motion path group.
    The SOP must have the standard two inputs for motion paths and agents.
    """
    path_geo = node.inputGeometry(0)
    crowd_geo = node.inputGeometry(1)
    if not path_geo or not crowd_geo:
        return (None, "")

    group_parm = node.parm('group')
    path_group_str = group_parm.evalAsString() if group_parm else ""

    # Easy case - all agents' paths are selected.
    if not path_group_str:
        return (crowd_geo, "")

    # The group parameter applies to the motion path geometry, so we need to
    # transfer it to the crowd geometry to find the relevant agents.
    # Rather than building a potentially enormous group string, just copy
    # the crowd geometry and add a new prim group.
    sop_category = hou.sopNodeTypeCategory()

    group_verb = sop_category.nodeVerb("groupcreate")
    group_verb.setParms({
        "groupname": "__selection",
        "basegroup": path_group_str
    })
    path_geo = path_geo.freeze(read_only=False, clone_data_ids=True)
    group_verb.execute(path_geo, [path_geo])

    # There is one path per agent.
    group_copy_verb = sop_category.nodeVerb("groupcopy")
    group_copy_verb.setParms({
        "primitives": True,
        "primgroups": "__selection",
        "points": False,
        "edges": False,
        "vertices": False,
        "groupnameconflict": "overwrite",
        "copyemptygroups": False
    })
    crowd_geo = crowd_geo.freeze(read_only=False, clone_data_ids=True)
    group_copy_verb.execute(crowd_geo, [crowd_geo, path_geo])

    return (crowd_geo, "__selection")


def findCrowdObject(dopnode):
    objects = dopnode.processedObjects()
    return objects[0] if objects else None

def findDopAgentDefinitions(node):
    """ Finds the unique agent definitions in the processed DOP object."""
    obj = findCrowdObject(node)
    return findAgentDefinitions(obj.geometry()) if obj else []

def findAgent(geo, group_str = ""):
    """ Finds the agent primitive from the given geometry, or returns None."""
    if not geo or not geo.iterPrims():
        return None

    if not group_str:
        prims = geo.iterPrims()
    else:
        try:
            prims = geo.globPrims(group_str)
        except hou.OperationFailed:
            return None

    if not prims:
        return None

    prim = prims[0]
    return prim if prim.type() == hou.primType.Agent else None


def findAgentDefinitions(geo, group_str="",
                         group_type=hou.geometryType.Primitives):
    """ Wrapper around hou.crowds.findAgentDefinitions that does some exception
        handling.
    """
    try:
        return hou.crowds.findAgentDefinitions(geo, group=group_str, group_type=group_type)
    except hou.OperationFailed:
        # If the user typed an invalid group string, we should just show an
        # empty menu instead of popping up an error window.
        return []

def buildMenuStringList(names):
    """ Duplicates each element in a list of strings.
        For example, ["walk", "run"] becomes ["walk", "walk", "run", "run"]
    """
    return [name for pair in zip(names, names) for name in pair]

def _buildClipMenu(defns, clip_properties_geo = None):
    clip_names = [clip.name() for defn in defns for clip in defn.clips()]

    if clip_properties_geo:
        clipname_attrib = clip_properties_geo.findPointAttrib("clipname")
        if clipname_attrib:
            clip_names.extend(clipname_attrib.strings())

    return buildMenuStringList(sorted(set(clip_names)))


def _unpackClipProperties(
        crowd_geo: hou.Geometry,
        group_str: str,
        group_type: Optional[hou.geometryType]) -> hou.Geometry:
    """
    Unpacks the clip properties from the agent definition.
    This is used for SOPs that don't have an explicit clip properties input,
    such as motion paths.
    """

    group_type_val = 0  # Guess from Group
    if group_type == hou.geometryType.Points:
        group_type_val = 1
    elif group_type == hou.geometryType.Primitives:
        group_type_val = 2

    unpack_verb = hou.sopNodeTypeCategory().nodeVerb("agentunpack")
    unpack_verb.setParms({
        "group": group_str,
        "grouptype": group_type_val,
        "output": 1,  # 1 -> "rest"
        "uniqueagentdefinitions": True,
        "applyagentxform": False,
        "unpackrestshapesfrom": 3,  # 3 -> "shapelib"
        "shapefilter": "__clipproperties__",
        "iterations": 2
    })

    clip_properties_geo = hou.Geometry()
    unpack_verb.execute(clip_properties_geo, [crowd_geo])
    return clip_properties_geo


def buildClipMenu(node, include_clip_properties=False,
                  clip_properties_input=-1, input_index=0, group_str="",
                  group_type=hou.geometryType.Primitives):
    """ Build a menu containing the available clip names for an agent."""
    defns = findInputAgentDefinitions(node,
                                      input_index=input_index,
                                      group_str=group_str,
                                      group_type=group_type)

    clip_properties_geo = None
    if include_clip_properties:
        if clip_properties_input >= 0:
            clip_properties_geo = node.inputGeometry(clip_properties_input)

        # Fetch from the agent definition if there isn't an explicit clip
        # properties input.
        input_geo = node.inputGeometry(input_index)
        if not clip_properties_geo and input_geo:
            clip_properties_geo = _unpackClipProperties(
                input_geo, group_str, group_type)

    return _buildClipMenu(defns, clip_properties_geo)


def buildMotionPathClipMenu(node: hou.SopNode) -> Sequence[str]:
    """
    Builds a menu containing the available clip names for the agents
    associated with the group of motion paths.
    The SOP must have the standard two inputs for motion paths and agents.
    """
    (crowd_geo, agent_group) = _buildMotionPathAgentGroup(node)
    if not crowd_geo:
        return []

    group_type = hou.geometryType.Primitives
    defns = findAgentDefinitions(
        crowd_geo, agent_group, group_type)

    clip_properties_geo = _unpackClipProperties(
        crowd_geo, agent_group, group_type)

    return _buildClipMenu(defns, clip_properties_geo)


def buildDopClipMenu(node):
    """ Build a menu containing the available clip names for an agent in the
        processed DOP object, including those defined in the clip properties.
    """
    obj = findCrowdObject(node)
    if not obj:
        return []

    defns = findAgentDefinitions(obj.geometry())
    clip_properties = obj.geometry("ClipProperties")

    return _buildClipMenu(defns, clip_properties)

def buildClipChannelMenu(node):
    """
    Build a menu containing the channel names from all of the agent's clips.
    """
    defns = findInputAgentDefinitions(node)

    channel_names = set()
    for defn in defns:
        for clip in defn.clips():
            channel_names.update(clip.channelNames())

    return buildMenuStringList(sorted(channel_names))

def buildDopStateMenu(node):
    """ Build a menu containing the states in the crowd simulation."""
    (_, state_names) = findStates(node.dopNetNode())

    return buildMenuStringList(state_names)


def buildChannelMenu(node):
    """ Build a menu containing the channel names from an agent's rig."""
    defns = findInputAgentDefinitions(node)

    channel_names = set()
    for defn in defns:
        rig = defn.rig()
        if not defn.rig():
            continue

        channel_names.update(
            [rig.channelName(i) for i in range(0, rig.channelCount())])

    return buildMenuStringList(sorted(channel_names))


def buildTransformMenu(node):
    """ Build a menu containing the transform names from an agent's rig."""
    defns = findInputAgentDefinitions(node)

    xform_names = set()
    for defn in defns:
        rig = defn.rig()
        if not defn.rig():
            continue

        xform_names.update(
                [rig.transformName(i) for i in range(0, rig.transformCount())])

    return buildMenuStringList(sorted(xform_names))

def _buildTransformGroupMenu(defns):
    group_names = set()
    for defn in defns:
        group_names.update([group.name() for group in defn.transformGroups()])

    return buildMenuStringList(sorted(group_names))

def buildTransformGroupMenu(node, input_index=0):
    """ Build a menu containing the available transform groups."""
    defns = findInputAgentDefinitions(node, input_index=input_index)
    return _buildTransformGroupMenu(defns)

def buildDopTransformGroupMenu(node):
    """ Build a menu containing the available transform groups for an agent in
        the processed DOP object.
    """
    defns = findDopAgentDefinitions(node)
    return _buildTransformGroupMenu(defns)


def buildMotionPathTransformGroupMenu(node: hou.SopNode) -> Sequence[str]:
    """
    Builds a menu containing the available transform groups for the agents
    associated with the group of motion paths.
    The SOP must have the standard two inputs for motion paths and agents.
    """
    (crowd_geo, agent_group) = _buildMotionPathAgentGroup(node)
    if not crowd_geo:
        return []

    defns = findAgentDefinitions(
        crowd_geo, agent_group, group_type=hou.geometryType.Primitives)
    return _buildTransformGroupMenu(defns)


def buildLayerMenu(node, frame=None):
    """ Build a menu containing the available layer names."""
    defns = findInputAgentDefinitions(node, frame=frame)

    layer_names = set()
    for defn in defns:
        layer_names.update([layer.name() for layer in defn.layers()])

    return buildMenuStringList(sorted(layer_names))


def buildShapeMenu(node, frame=None):
    """ Build a menu containing the available shape names."""
    defns = findInputAgentDefinitions(node, frame=frame)

    shape_names = set()
    for defn in defns:
        shape_names.update(
            [shape.name() for shape in defn.shapeLibrary().shapes()])

    return buildMenuStringList(sorted(shape_names))


def buildShapeDeformerMenu():
    """ Build a menu containing the available shape deformer names."""
    deformer_names = [d.name() for d in hou.crowds.shapeDeformers()]
    # The output of hou.crowds.shapeDeformers() is already sorted by name.
    return buildMenuStringList(deformer_names)


def buildMetadataMenu(node, input_index=0, group_parm=None):
    """ Build a menu containing the available metadata keys."""
    group_str = node.evalParm(group_parm) if group_parm else None
    defns = findInputAgentDefinitions(node, input_index=input_index, group_str=group_str)
    metadatas = set()
    for defn in defns:
        metadata = defn.metadata()
        metadatas.update(metadata.data().keys() if metadata and metadata.data() else [])
    return buildMenuStringList(sorted(metadatas))


def selectFromTreeView(node, parmtuple, names, paths, exclusive=True):
    """ Edit a parm via a tree chooser that selects from a list of paths."""

    if not names:
        return

    # Find the paths that should initially be selected.
    current_pattern = parmtuple.evalAsStrings()[0]
    initial_selection = []
    for i, name in enumerate(names):
        if hou.text.patternMatch(current_pattern, name):
            initial_selection.append(paths[i])

    selection = hou.ui.selectFromTree(paths,
                                      picked=initial_selection,
                                      exclusive=exclusive)
    # Update the parm value if the selection changed.
    if selection and list(selection) != initial_selection:
        path_index = {path: i for i, path in enumerate(paths)}

        selected_names = [names[path_index[path]] for path in selection]
        parmtuple.set((" ".join(selected_names), ))


def selectJoint(node, parmtuple, exclusive=True):
    """ Open a tree chooser to select a joint name."""
    defns = findInputAgentDefinitions(node)
    if not defns:
        raise hou.Error("Geometry does not contain any agent primitives")

    rig = defns[0].rig()

    names = list(rig.transformNames())

    full_paths = [None] * rig.transformCount()
    queue = []
    for i in range(0, rig.transformCount()):
        if rig.parentIndex(i) < 0:
            queue.append(i)

    while len(queue) > 0:
        xform_idx = queue.pop(0)
        xform_name = names[xform_idx]

        parent_xform_idx = rig.parentIndex(xform_idx)
        if parent_xform_idx >= 0:
            parent_path = full_paths[parent_xform_idx]
        else:
            parent_path = ""

        full_path = parent_path + "/" + xform_name
        full_paths[xform_idx] = full_path

        for child_idx in rig.childIndices(xform_idx):
            queue.append(child_idx)

    selectFromTreeView(node, parmtuple, names, full_paths, exclusive=exclusive)


def _findInputNamesFromParm(node,
                            parm_name,
                            invalid_node_types=None,
                            known_nodes=None):
    result = []
    if not node:
        return result

    # Avoid recursion.
    if not known_nodes:
        known_nodes = set()
    elif node in known_nodes:
        return result

    known_nodes.add(node)
    base_type = toolutils.nodeTypeNameBase(node)

    # Special case to correctly follow switches.
    if base_type == "switch":
        sel_input = node.parm("input").eval()
        if sel_input < 0 or sel_input >= len(node.inputs()):
            return []
        else:
            input_node = node.inputs()[sel_input]
            return _findInputNamesFromParm(input_node, parm_name,
                                           invalid_node_types, known_nodes)
    # Warn about input nodes that aren't sensible.
    elif invalid_node_types and base_type in invalid_node_types:
        raise hou.Error("Invalid input: {0}".format(node.path()))
    # Stop when we hit a node with the parm, otherwise keep searching.
    else:
        parm = node.parm(parm_name)
        name = parm.evalAsString() if parm else None

        if name:
            result.append(name)
        else:
            for input_node in node.inputs():
                result += _findInputNamesFromParm(input_node, parm_name,
                                                  invalid_node_types,
                                                  known_nodes)

    return result


def findInputStateNames(node, known_nodes=None):
    """
    Return a list of the crowd states that the DOP is operating on, via its
    inputs. This is similar to opstreamname, but uses the 'statename' parameter
    and doesn't generate a group string.
    """
    return _findInputNamesFromParm(node, "statename")


# It doesn't make sense to allow a transition or state to be the input of a
# trigger.
INVALID_INTERMEDIATE_TYPES = frozenset([
    "crowdtransition",
    "crowdstate"
])


def findInputTriggerName(node, input_index=0):
    """
    Find the name of the trigger point attribute generated by the input node.
    """
    if input_index >= len(node.inputs()) or not node.inputs()[input_index]:
        return ""

    input_node = node.inputs()[input_index]
    # Trigger nodes are expected to have a "triggerattrib" parm specifying the
    # attribute containing the trigger value.
    names = _findInputNamesFromParm(input_node, "triggerattrib",
                                    INVALID_INTERMEDIATE_TYPES)
    if not names:
        raise hou.Error("No input trigger found.")
    elif len(names) > 1:
        raise hou.Error("Found multiple input triggers.")

    return names[0]


def computeRotationLimits(node, instance):
    """ Determine joint limits by analyzing the agent's animation clips.
    """
    xform_name = node.parm("transform_name{0}".format(instance)).evalAsString()
    parent_xform_name = node.parm(
            "parent_transform_name{0}".format(instance)).evalAsString()

    agent = findInputAgent(node)
    rig = agent.rig() if agent else None
    if not rig:
        return

    clip_pattern = node.parm("clip_names").evalAsString()
    clips = [clip for clip in agent.clipCatalog()
             if hou.text.patternMatch(clip_pattern, clip.name())]
    if not clips:
        raise hou.Error("No clips were selected.")

    xform_idx = rig.findTransform(xform_name)
    parent_xform_idx = rig.findTransform(parent_xform_name)
    if xform_idx < 0 or parent_xform_idx < 0:
        return

    result = hou.crowds.computeRotationLimits(rig, clips, xform_idx,
                                              parent_xform_idx)

    # Update the parameters.
    node.parmTuple("offset{0}".format(instance)).set(result["anchor_pos"])
    node.parmTuple("child_r{0}".format(instance)).set(result["child_rotation"])
    node.parmTuple("twist_range{0}".format(instance)).set(result["twist_limits"])
    node.parmTuple("up_range{0}".format(instance)).set(result["up_limits"])
    node.parmTuple("out_range{0}".format(instance)).set(result["out_limits"])
    node.parmTuple("r{0}".format(instance)).set(result["rotation"])

def createLimitsForCollisionLayer(node):
    """ Add an auto-computed joint limit for each non-root transform with a
        shape attached to it in the collision layer.
    """
    agent = findInputAgent(node)
    rig = agent.rig() if agent else None
    if not rig:
        return

    layers = agent.collisionLayers()
    if not layers:
        raise hou.Error("Agent does not have any collision layers.")

    # Clear the multiparm.
    multiparm = node.parm("num_limits")
    for i in reversed(list(range(0, multiparm.evalAsInt()))):
        multiparm.removeMultiParmInstance(i)

    # Inspect the collision layer and figure out which transforms to set joint
    # limits for.
    xforms_with_shapes = set()
    for layer in layers:
        for binding in layer.bindings():
            xform_idx = binding.transformId()
            if binding.isDeforming() or xform_idx < 0:
                continue

            xforms_with_shapes.add(xform_idx)

    xform_list = []
    for xform_idx in xforms_with_shapes:
        # Check if the transform has a parent with a shape attached to it.
        parent_idx = xform_idx
        while True:
            parent_idx = rig.parentIndex(parent_idx)
            if parent_idx < 0:
                break

            if parent_idx in xforms_with_shapes:
                xform_list.append(xform_idx)
                break

    # Add multiparm instances.
    for instance, xform_idx in enumerate(xform_list):
        multiparm.insertMultiParmInstance(instance)

        # Note that the callback on the transform_name parameter will trigger
        # computeRotationLimits().
        xform_name = rig.transformName(xform_idx)
        node.parm("transform_name{0}".format(instance)).set(xform_name)
