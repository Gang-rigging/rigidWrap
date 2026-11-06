"""Maya-side GPU override diagnostics for rigidWrap.

Run inside Maya's Script Editor:

    import rigidWrapGpuCheck
    rigidWrapGpuCheck.run("rigidWrap1")
"""

from __future__ import print_function

import pprint
import os
import statistics
import time

import maya.cmds as cmds
import maya.mel as mel


def _safe(callable_obj, default=None):
    try:
        return callable_obj()
    except Exception as exc:  # Maya commands report useful text in exceptions.
        if default is not None:
            return default
        return "{}: {}".format(type(exc).__name__, exc)


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _option_var(name):
    if not cmds.optionVar(exists=name):
        return None
    return cmds.optionVar(query=name)


def _deformer_clusters(raw_clusters):
    raw_clusters = _as_list(raw_clusters)
    clusters = []
    index = 0
    while index < len(raw_clusters):
        try:
            count = int(raw_clusters[index])
        except (TypeError, ValueError):
            break
        start = index + 1
        stop = start + count
        if count < 0 or stop > len(raw_clusters):
            break
        clusters.append(raw_clusters[start:stop])
        index = stop
    return clusters


def _flatten(clusters):
    result = []
    for cluster in clusters:
        result.extend(cluster)
    return result


def _model_panel_renderers():
    result = {}
    for panel in cmds.getPanel(type="modelPanel") or []:
        result[panel] = _safe(
            lambda panel=panel: cmds.modelEditor(panel, query=True, rendererName=True)
        )
    return result


def _rigidwrap_plugin():
    """Identify the loaded plugin defining rigidWrap without loading anything."""
    for plugin in cmds.pluginInfo(query=True, listPlugins=True) or []:
        node_types = _safe(
            lambda plugin=plugin: cmds.pluginInfo(plugin, query=True, dependNode=True),
            [],
        ) or []
        if "rigidWrap" not in node_types:
            continue
        path = cmds.pluginInfo(plugin, query=True, path=True)
        result = {
            "name": plugin,
            "path": path,
            "version": cmds.pluginInfo(plugin, query=True, version=True),
            "file_size": None,
            "mtime_ns": None,
        }
        # These describe the file currently at Maya's loaded path. The version
        # comes from the loaded plugin, even if that file was replaced on disk.
        try:
            stat = os.stat(path)
            result.update(file_size=stat.st_size, mtime_ns=stat.st_mtime_ns)
        except OSError as exc:
            result["file_stat_error"] = str(exc)
        return result
    return None


def _force_vp2():
    for panel in cmds.getPanel(type="modelPanel") or []:
        _safe(lambda panel=panel: cmds.modelEditor(panel, edit=True, rendererName="vp2Renderer"))


def _node_settings(node):
    attrs = [
        "blockGPU",
        "collisionThickness",
        "maxSlide",
        "maxLift",
        "attachmentStrength",
        "normalOffset",
        "rotationStrength",
        "rotationStability",
        "scaleX",
        "scaleY",
        "scaleZ",
        "relaxation",
        "relaxationIterations",
        "tangentBlend",
        "collisionScale",
        "collisionStrength",
        "collisionIterations",
        "collisionLift",
        "collisionSoftness",
        "collisionMode",
    ]
    settings = {}
    # Bind records may contain millions of samples. Keep console diagnostics small.
    bind_text = _safe(lambda: cmds.getAttr(node + ".bindData"), "") or ""
    settings["bindData"] = {"header": bind_text.partition("\n")[0][:160], "characters": len(bind_text)}
    for attr in attrs:
        plug = "{}.{}".format(node, attr)
        settings[attr] = _safe(lambda plug=plug: cmds.getAttr(plug), None) if cmds.objExists(plug) else None
    animated = {}
    for attr in attrs:
        plug = "{}.{}".format(node, attr)
        if not cmds.objExists(plug):
            continue
        inputs = _safe(
            lambda plug=plug: cmds.listConnections(
                plug,
                source=True,
                destination=False,
                plugs=True,
            ),
            [],
        ) or []
        key_count = _safe(lambda plug=plug: cmds.keyframe(plug, query=True, keyframeCount=True), 0) or 0
        if inputs or key_count:
            animated[attr] = {
                "inputs": inputs,
                "keyCount": key_count,
            }
    settings["animatedConditionalAttrs"] = animated
    settings["driverMesh"] = _safe(
        lambda: cmds.listConnections(
            "{}.driverMesh".format(node),
            source=True,
            destination=False,
            plugs=True,
        )
    )
    settings["geometry"] = _safe(lambda: cmds.deformer(node, query=True, geometry=True))
    return settings


def activate(force_vp2=True, disable_min_vertex_limit=True):
    """Enable Maya's GPU Override the same way the Evaluation Toolkit does."""

    _safe(lambda: cmds.loadPlugin("deformerEvaluator", quiet=True))
    _safe(lambda: cmds.loadPlugin("GPUBuiltInDeformer", quiet=True))
    _safe(lambda: cmds.evaluationManager(mode="parallel"))

    # Autodesk's UI does both: set the optionVar and call this MEL proc.
    # The proc toggles the deformer evaluator and forces an EM refresh.
    try:
        from maya.app.evaluationToolkit.evaluation_toolkit_utilities import (
            set_gpu_override_active,
        )

        set_gpu_override_active(True)
    except Exception:
        mel.eval("optionVar -iv gpuOverride 1")
        mel.eval("turnOnOpenCLEvaluatorActive();")

    _safe(lambda: cmds.evaluator(name="deformer", enable=True))
    if disable_min_vertex_limit:
        _safe(lambda: cmds.deformerEvaluator(limitMinimumVerts=False))
    if force_vp2:
        _force_vp2()

    _safe(lambda: cmds.evaluationManager(invalidate=True))
    _safe(lambda: cmds.currentTime(cmds.currentTime(query=True)))
    _safe(lambda: cmds.refresh(force=True))


def collect(node=None, activate_override=True, force_vp2=True):
    """Return a dictionary with the important GPU override state."""

    if activate_override:
        activate(force_vp2=force_vp2)

    nodes = _as_list(node) if node else (cmds.ls(type="rigidWrap") or [])
    raw_clusters = _safe(lambda: cmds.evaluator(name="deformer", query=True, clusters=True), [])
    clusters = _deformer_clusters(raw_clusters)
    active_nodes = _as_list(
        _safe(lambda: cmds.deformerEvaluator(query=True, act=True, nm=True), [])
    )
    active_statuses = (
        _safe(lambda: cmds.deformerEvaluator(active_nodes, query=True, ns=True), [])
        if active_nodes
        else []
    )
    checked_statuses = (
        _safe(lambda: cmds.deformerEvaluator(nodes, query=True, ns=True), [])
        if nodes
        else []
    )

    return {
        "rigidWrap_plugin": _rigidwrap_plugin(),
        "gpuOverride_optionVar": _option_var("gpuOverride"),
        "deformerEvaluator_plugin_loaded": _safe(
            lambda: cmds.pluginInfo("deformerEvaluator", query=True, loaded=True)
        ),
        "gpuBuiltInDeformer_plugin_loaded": _safe(
            lambda: cmds.pluginInfo("GPUBuiltInDeformer", query=True, loaded=True)
        ),
        "evaluation_mode": _safe(lambda: cmds.evaluationManager(query=True, mode=True)),
        "deformer_evaluator_active": _safe(lambda: mel.eval('isEvaluatorActive("deformer")')),
        "model_panel_renderers": _model_panel_renderers(),
        "checked_nodes": nodes,
        "checked_node_settings": {item: _node_settings(item) for item in nodes},
        "raw_clusters": raw_clusters,
        "clusters": clusters,
        "claimed_nodes": _flatten(clusters),
        "active_nodes": active_nodes,
        "active_statuses": active_statuses,
        "checked_statuses": checked_statuses,
    }


def run(node=None, activate_override=True, force_vp2=True):
    """Print GPU override diagnostics and return the collected dictionary."""

    data = collect(
        node=node,
        activate_override=activate_override,
        force_vp2=force_vp2,
    )
    print("# rigidWrap GPU check")
    print(pprint.pformat(data, width=120))
    return data


def benchmark_viewport(node, frames=30):
    """Opt-in short viewport scrub comparison; returns timings and GPU status.

    Run in interactive Maya with collision disabled. This measures the whole
    visible scene, including drawing, rather than isolated rigidWrap evaluation.
    GPU allowed does not mean GPU active: inspect each result's gpu_active and
    diagnostics. Evaluation mode, animation, connections and solver settings
    are preserved. Only blockGPU and current time change temporarily.
    """
    if isinstance(frames, bool) or not isinstance(frames, int) or not 1 <= frames <= 60:
        raise ValueError("frames must be an integer from 1 to 60.")
    result = {"status": "unsupported", "node": node, "runs": []}
    if cmds.about(batch=True):
        result["reason"] = "Viewport timing requires interactive Maya; batch/standalone has no viewport."
        return result
    matches = cmds.ls(node, type="rigidWrap") or []
    if len(matches) != 1:
        result["reason"] = "Choose exactly one existing rigidWrap node."
        return result
    node = matches[0]
    result["node"] = node
    panels = set(cmds.getPanel(type="modelPanel") or [])
    visible = set(cmds.getPanel(visiblePanels=True) or [])
    if not panels.intersection(visible):
        result["reason"] = "Open a visible model viewport before benchmarking."
        return result
    block_plug = node + ".blockGPU"
    if (not cmds.objExists(block_plug) or cmds.getAttr(block_plug, lock=True) or
            cmds.listConnections(block_plug, source=True, destination=False) or
            not cmds.getAttr(block_plug, settable=True)):
        result["reason"] = "blockGPU must be unlocked and have no incoming connection."
        return result
    original_frame = cmds.currentTime(query=True)
    original_block = cmds.getAttr(block_plug)
    sample_frames = [original_frame + index + 1 for index in range(frames)]
    # Query only scalar controls in timed contexts. Never read output mesh data,
    # which would force GPU readback, or step into an expensive collision frame.
    for frame in [original_frame] + sample_frames:
        size = cmds.getAttr(node + ".collisionScale", time=frame)
        strength = cmds.getAttr(node + ".collisionStrength", time=frame)
        if size > 0 and strength > 0:
            result.update(status="collision_active", collision_frame=frame,
                          settings=_node_settings(node),
                          reason="Disable collision for the sampled frames, then run again. "
                                 "No collision settings or animation were changed.")
            return result
    result.update(status="complete", sample_frames=sample_frames,
                  scope="Whole visible scene: currentTime plus forced viewport refresh; "
                        "not isolated deformer FPS. Cached playback and other Maya settings are unchanged.")
    deadline = time.perf_counter() + 15.0
    try:
        for blocked in (False, True):
            cmds.setAttr(block_plug, blocked)
            # Warm the graph and shaders after toggling blockGPU, outside timing.
            for frame in sample_frames[:min(3, frames)]:
                cmds.currentTime(frame)
                cmds.refresh(force=True)
                if time.perf_counter() >= deadline:
                    break
            durations = []
            for frame in sample_frames:
                if time.perf_counter() >= deadline:
                    break
                start = time.perf_counter()
                cmds.currentTime(frame)
                cmds.refresh(force=True)
                durations.append(time.perf_counter() - start)
            diagnostics = collect(node, activate_override=False, force_vp2=False)
            entry = {"requested_mode": "GPU blocked" if blocked else "GPU allowed",
                     "gpu_active": node in diagnostics["active_nodes"],
                     "sample_count": len(durations), "diagnostics": diagnostics}
            if durations:
                median = statistics.median(durations)
                entry.update(median_frame_ms=median * 1000.0,
                             mean_frame_ms=sum(durations) / len(durations) * 1000.0,
                             viewport_scrub_fps=1.0 / median if median > 0 else None)
            result["runs"].append(entry)
            if time.perf_counter() >= deadline:
                result.update(status="time_limit", reason="Stopped between frames after the 15-second "
                              "budget. A single Maya evaluation cannot be interrupted by this helper.")
                break
    except Exception as exc:
        result.update(status="error", reason="{}: {}".format(type(exc).__name__, exc))
    finally:
        restoration_errors = []
        for restore in (lambda: cmds.setAttr(block_plug, original_block),
                        lambda: cmds.currentTime(original_frame)):
            try:
                restore()
            except Exception as exc:
                restoration_errors.append(str(exc))
        if restoration_errors:
            result.update(status="restore_error", restoration_errors=restoration_errors)
    print("# rigidWrap viewport benchmark")
    print(pprint.pformat(result, width=120))
    return result
