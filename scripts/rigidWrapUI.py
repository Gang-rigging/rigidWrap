from __future__ import annotations

import json
import math

import maya.cmds as cmds
import maya.OpenMayaUI as omui
try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import wrapInstance
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from shiboken2 import wrapInstance

_WINDOW = None


_USER_GUIDE_URL = "https://www.cgdzg.com/docs/rigidWrap_User_Guide.html"
_REPORT_ISSUE_URL = "https://github.com/Gang-rigging/rigidWrap/issues/"


def _maya_main_window():
    pointer = omui.MQtUtil.mainWindow()
    return wrapInstance(int(pointer), QtWidgets.QWidget) if pointer else None


def plugin_ready():
    commands = ("rigidWrapBind", "rigidWrapCreateProxy", "rigidWrapDebugDraw")
    if all(hasattr(cmds, command) for command in commands):
        return True
    try:
        cmds.loadPlugin("rigidWrap", quiet=True)
    except RuntimeError:
        pass
    if all(hasattr(cmds, command) for command in commands):
        return True
    raise RuntimeError("Load the rigidWrap plugin before using this tool.")


def first_rigid_wrap_from_node(node):
    if not node or not cmds.objExists(node):
        return ""
    if cmds.nodeType(node) == "rigidWrap":
        return node
    return next((item for item in cmds.listHistory(node, pruneDagObjects=True) or []
                 if cmds.nodeType(item) == "rigidWrap"), "")


def selected_rigid_wrap():
    for item in cmds.ls(selection=True, long=True, objectsOnly=True) or []:
        node = first_rigid_wrap_from_node(item)
        if node:
            return node
    return ""


def _combo(items):
    widget = QtWidgets.QComboBox()
    for label, value in items:
        widget.addItem(label, value)
    return widget


def _number(minimum, maximum, value, integer=False):
    widget = QtWidgets.QSpinBox() if integer else QtWidgets.QDoubleSpinBox()
    if integer:
        minimum, maximum = int(max(-2147483647, minimum)), int(min(2147483647, maximum))
    else:
        widget.setDecimals(6)
        widget.setSingleStep(0.1)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    return widget


def _note(text):
    label = QtWidgets.QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(QtCore.Qt.PlainText)
    return label


def _expanded_bind_data(text, rings=2, max_pairs=1000000):
    """Expand stored collision paths using a frozen bind graph and rest centers.

    Samples, island records, and spacing links are kept byte-for-byte. Only
    collision records change; repeated calls expand the updated graph further.
    """
    if isinstance(rings, bool) or not isinstance(rings, int) or not 1 <= rings <= 3:
        raise ValueError("Collision neighbor rings must be an integer from 1 to 3.")
    if isinstance(max_pairs, bool) or not isinstance(max_pairs, int) or max_pairs < 1:
        raise ValueError("Collision pair limit must be a positive integer.")
    if not isinstance(text, str) or text.partition("\n")[0].split() != ["rigidWrapBind", "103"]:
        raise ValueError("Collision expansion requires current bind data. Rebind with rigidWrapBind.")
    lines = text.splitlines(keepends=True)
    centers, edges, distances = {}, set(), {}
    start, island_count = None, None
    for index, line in enumerate(lines):
        tokens = line.split()
        if not tokens:
            continue
        if tokens[0] == "islandCount":
            if island_count is not None or len(tokens) != 2:
                raise ValueError("Invalid island count.")
            island_count = int(tokens[1])
            if island_count < 1:
                raise ValueError("Invalid island count.")
        elif tokens[0] == "island":
            if len(tokens) < 6 or "center" not in tokens:
                raise ValueError("Invalid bind center.")
            position, island_id = tokens.index("center") + 1, int(tokens[1])
            if island_id in centers:
                raise ValueError("Duplicate island.")
            center = tuple(map(float, tokens[position:position + 3]))
            if len(center) != 3 or not all(math.isfinite(value) for value in center):
                raise ValueError("Invalid bind center.")
            centers[island_id] = center
        elif tokens[0] == "collisionEdgeCount":
            if start is not None or len(tokens) != 2:
                raise ValueError("Invalid collision graph header.")
            start, declared = index, int(tokens[1])
            if declared < 0 or declared > max_pairs:
                raise ValueError("Collision graph exceeds the pair limit.")
        elif tokens[0] == "collisionEdge":
            if start is None or len(tokens) != 4:
                raise ValueError("Invalid collision edge.")
            a, b = map(int, tokens[1:3])
            if a == b or a not in centers or b not in centers:
                raise ValueError("Invalid collision edge.")
            pair = tuple(sorted((a, b)))
            if pair in edges:
                raise ValueError("Duplicate collision edge.")
            edges.add(pair)
            distances[pair] = float(tokens[3])
            if not math.isfinite(distances[pair]) or distances[pair] <= 0:
                raise ValueError("Invalid collision edge distance.")
    if start is None:
        raise ValueError("Missing collision graph.")
    if (island_count is None or len(centers) != island_count or
            any(index < 0 or index >= island_count for index in centers)):
        raise ValueError("Island count does not match bind data.")
    if any(line.strip() and not line.startswith("collisionEdge ") for line in lines[start + 1:]):
        raise ValueError("Unexpected data after collision graph.")
    if declared != sum(line.startswith("collisionEdge ") for line in lines[start + 1:]):
        raise ValueError("Collision edge count does not match bind data.")
    adjacency = {index: set() for index in centers}
    for a, b in edges:
        adjacency[a].add(b)
        adjacency[b].add(a)
    expanded = set(edges)
    for a in sorted(adjacency):
        seen, frontier = {a}, {a}
        for _ in range(rings):
            frontier = {b for neighbor in frontier for b in adjacency[neighbor]} - seen
            seen.update(frontier)
            expanded.update((min(a, b), max(a, b)) for b in frontier)
            if len(expanded) > max_pairs:
                raise ValueError("Expanded collision graph exceeds the %d-pair limit." % max_pairs)
    skipped = 0
    for a, b in list(expanded - edges):
        dx, dy, dz = (x - y for x, y in zip(centers[a], centers[b]))
        distance = math.hypot(math.hypot(dx, dy), dz)
        if not math.isfinite(distance):
            raise ValueError("Expanded collision edge distance is not finite.")
        if distance <= 1e-9:
            expanded.remove((a, b))
            skipped += 1
        else:
            distances[(a, b)] = distance
    summary = dict(before=len(edges), after=len(expanded), added=len(expanded) - len(edges),
                   rings=rings, coincident_skipped=skipped)
    if expanded == edges:
        return text, summary
    records = ["collisionEdgeCount %d\n" % len(expanded)]
    for a, b in sorted(expanded):
        records.append("collisionEdge %d %d %.17g\n" % (a, b, distances[(a, b)]))
    return "".join(lines[:start] + records), summary


def _expand_collision_neighbors(node, rings=2):
    """Edit only the stored collision graph in one Maya undo chunk."""
    if not cmds.objExists(node) or cmds.nodeType(node) != "rigidWrap":
        raise ValueError("Select a bound rigidWrap node.")
    plug = node + ".bindData"
    if not cmds.getAttr(plug, settable=True):
        raise ValueError("Bind data is locked or connected.")
    original = cmds.getAttr(plug)
    updated, summary = _expanded_bind_data(original, rings)
    if updated != original:
        cmds.undoInfo(openChunk=True, chunkName="Expand rigidWrap collision neighbors")
        try:
            cmds.setAttr(plug, updated, type="string")
        finally:
            cmds.undoInfo(closeChunk=True)
    return summary


class RigidWrapWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rigidWrapPySideWindow")
        self.setWindowTitle("rigidWrap")
        self.resize(480, 520)
        self.setMinimumSize(440, 400)
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)
        self._preset_update = False
        self._node_entries = None
        self.foldouts = {}
        self.status_label = _note("Choose your meshes, then Bind.")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        self.menu_bar = QtWidgets.QMenuBar(self)
        self.menu_bar.setNativeMenuBar(False)
        # Keep an explicitly parented menu wrapper. PySide2 can otherwise
        # release a menu returned by addMenu(str) during QAction.menu() lookup.
        self.help_menu = QtWidgets.QMenu("Help", self.menu_bar)
        self.menu_bar.addMenu(self.help_menu)
        self.user_guide_action = self.help_menu.addAction("User Guide")
        self.user_guide_action.setToolTip("Open the online user guide in your browser (internet required).")
        self.user_guide_action.triggered.connect(self.show_user_guide)
        self.report_issue_action = self.help_menu.addAction("Report Issue")
        self.report_issue_action.setToolTip("Open the rigidWrap GitHub issue tracker in your browser.")
        self.report_issue_action.triggered.connect(self.report_issue)
        layout.setMenuBar(self.menu_bar)
        self.active_header = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(self.active_header)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QtWidgets.QLabel("Active node"))
        self.active_node = QtWidgets.QComboBox()
        self.active_node.setMinimumContentsLength(16)
        self.active_node.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.active_node, 1)
        row.addWidget(self._button("Use Selected", self.use_selected_node,
                                  "Select a rigidWrap node or driven mesh in Maya, then click here."))
        layout.addWidget(self.active_header)
        self.active_node.setToolTip("Tools use this node. Viewport selection will not switch it.")
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_bind_tab()
        self._build_tools_tab()
        self._add_tooltips()
        self.tabs.currentChanged.connect(lambda index: self.active_header.setVisible(index != 0))
        self.active_header.setVisible(False)
        layout.addWidget(self.status_label)
        self.refresh_nodes(preferred=selected_rigid_wrap())
        self._update_bind_state()
        # Poll while visible; no Maya scriptJobs survive a closed window.
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(750)
        self._timer.timeout.connect(self._refresh_scene)

    def _button(self, label, callback, tooltip=""):
        button = QtWidgets.QPushButton(label)
        button.setToolTip(tooltip)
        button.clicked.connect(lambda checked=False: self._run(callback))
        return button

    def show_user_guide(self, *_):
        return self._open_help_url(_USER_GUIDE_URL, "user guide")

    def report_issue(self, *_):
        return self._open_help_url(_REPORT_ISSUE_URL, "issue tracker")

    def _open_help_url(self, url, label):
        opened = QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
        if opened:
            self._set_status("Opened the " + label + " in your browser.")
        else:
            self._set_status("Could not open the browser. Visit " + url, error=True)
        return opened

    def _add_tooltips(self):
        tips = {
            "active_node": "The rigidWrap node used by contact reports, proxies, and debug drawing. Choose a node here or use Use Selected; changing viewport selection does not switch this target.",
            "driven_mesh": "The mesh containing the rigid islands you want to attach. Each disconnected mesh shell becomes one rigid island. Choose its shape or a transform with one visible mesh.",
            "driver_mesh": "The deforming surface the islands will follow. Bind both meshes in their intended rest pose. The driver must be different from the driven mesh.",
            "preset": "Starting settings for the next bind. General Surface uses global regions. Local Patch keeps driver samples and spacing local. Custom preserves your Advanced binding settings. Existing nodes are not changed.",
            "sample_count": "Attachment samples per island: default 16, UI range 1–64, limited by the island's vertex count. More samples cost more and can span a larger area; they do not always improve the fit.",
            "neighbor_count": "Neighbors requested per island for the fixed spacing and collision graph stored at bind time; default 6. More neighbors couple more islands and increase work. Increasing this setting requires rebinding to add collision links to an existing setup.",
            "neighbor_radius": "Maximum bind-pose distance for finding stored neighbors, in world-space scene units. 0 means Unlimited. Smaller values restrict spacing and collision links. Rebind to add excluded links.",
            "driver_region_mode": "Global searches the driver surface. Local Patch limits attachment samples to connected faces around the closest-face anchor, helping separate nearby sides of a gap. Driver rings sets the patch size.",
            "driver_region_rings": "Connected driver-face steps allowed for Local Patch samples; default 12. 0 uses the anchor face, 1 includes edge neighbors. More rings cover more surface and can reach around a gap. Ignored in Global mode.",
            "spacing_region_mode": "Global allows spacing links across the driver. Driver Patch restricts links to islands whose anchor faces are reachable within Spacing rings, helping nearby surface regions relax independently.",
            "spacing_region_rings": "Connected driver-face steps allowed between spacing anchors; default 8. More rings permit farther spacing neighbors. These are topology steps, not a world-space distance. Used only with Driver Patch.",
            "collision_region_mode": "Filters the fixed collision graph stored at bind time. Global allows links across the driver; Driver Patch restricts them by connected faces. Excluded pairs will not collide, even if they meet later. Rebind to add links.",
            "collision_region_rings": "Connected driver-face steps allowed between stored collision anchors; default 8. More rings permit farther neighbors. Used only with Driver Patch. Changing the stored collision graph requires rebinding.",
            "proxy_scale": "Scales island geometry before proxy reduction; 1 uses the original size. Reduced vertices are then projected back to the source surface. This setting affects the new proxy, not the original mesh.",
            "proxy_max_vertices": "Reduction budget per island; default 16, minimum 3. Smaller values produce a lighter proxy. Reduction uses a total mesh budget, so individual island counts may vary.",
            "proxy_name": "Name for the new proxy transform. Leave blank to generate a name from the active rigidWrap node. Maya resolves name clashes.",
            "debug_mode": "Choose the collision shapes to visualize. Current footprint uses the node's active collision mode; the other choices preview a specific shape or all shapes. This does not change the collision solver mode.",
            "show_edges": "Show stored spacing-neighbor links between islands. Collision can use different stored links when its bind region settings differ from spacing.",
            "xray": "Draw debug lines through other geometry so hidden shapes and links are visible. Turn off to respect viewport depth.",
            "show_lift": "Show outward-lift correction arrows. Requires Solve Collision Debug on the debug locator. This only displays lift; Collision Lift on the deformer controls whether the solver generates it.",
        }
        for name, tip in tips.items():
            widget = getattr(self, name)
            widget.setToolTip(("Next bind only. " if widget in self.bind_controls else "") + tip)
        # Hovering an enabled label also explains a currently disabled field.
        for form in self.findChildren(QtWidgets.QFormLayout):
            for row in range(form.rowCount()):
                label = form.itemAt(row, QtWidgets.QFormLayout.LabelRole)
                field = form.itemAt(row, QtWidgets.QFormLayout.FieldRole)
                if not label or not label.widget() or not field:
                    continue
                widget = field.widget()
                if not widget and field.layout():
                    widget = field.layout().itemAt(0).widget()
                if widget and widget.toolTip():
                    label.widget().setToolTip(widget.toolTip())
        self.active_header.findChild(QtWidgets.QLabel).setToolTip(self.active_node.toolTip())
        self.tabs.setTabToolTip(0, "Choose the driven mesh and driver, then create a bind in the rest pose.")
        self.tabs.setTabToolTip(1, "Check contacts, create an animation proxy, or manage viewport debug drawing for the active node.")
        self.status_label.setToolTip("Result of the most recent action, including any input or command error.")

    def _run(self, callback):
        try:
            return callback()
        except (RuntimeError, ValueError, TypeError) as error:
            self._set_status(str(error), error=True)
            return None

    def _set_status(self, text, error=False):
        self.status_label.setText(("Could not complete: " if error else "") + text)

    def _page(self, title):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setSpacing(12)
        scroll.setWidget(page)
        if title == "Bind":
            container = QtWidgets.QWidget()
            outer = QtWidgets.QVBoxLayout(container)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.addWidget(scroll, 1)
            self.bind_footer = QtWidgets.QVBoxLayout()
            outer.addLayout(self.bind_footer)
            self.tabs.addTab(container, title)
        else:
            self.tabs.addTab(scroll, title)
        return layout

    def _group(self, layout, title):
        group = QtWidgets.QGroupBox(title)
        form = QtWidgets.QFormLayout(group)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        layout.addWidget(group)
        return form

    def _foldout(self, layout, title, tooltip):
        button = QtWidgets.QToolButton()
        button.setText(title)
        button.setToolTip(tooltip)
        button.setCheckable(True)
        button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        button.setArrowType(QtCore.Qt.RightArrow)
        content = QtWidgets.QWidget()
        inner = QtWidgets.QVBoxLayout(content)
        inner.setContentsMargins(0, 0, 0, 0)
        content.hide()
        button.toggled.connect(content.setVisible)
        button.toggled.connect(lambda expanded: button.setArrowType(
            QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow))
        layout.addWidget(button)
        layout.addWidget(content)
        self.foldouts[title] = (button, content)
        return inner

    def _build_bind_tab(self):
        layout = self._page("Bind")
        layout.addWidget(_note("Bind in the rest pose. Collision uses stored bind neighbors; new binds use Capsule shapes."))
        form = self._group(layout, "Meshes")
        self.driven_mesh, self.driver_mesh = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        for label, field in (("Driven mesh", self.driven_mesh), ("Driver mesh", self.driver_mesh)):
            field.setPlaceholderText("Choose a mesh from the scene")
            row = QtWidgets.QHBoxLayout()
            row.addWidget(field, 1)
            row.addWidget(self._button("Use Selected", lambda field=field: self.capture_mesh(field),
                                      "Use the one selected Maya mesh as the {}. This fills the field without binding.".format(label.lower())))
            form.addRow(label, row)
        self.preset = _combo([("General Surface", "general"), ("Local Patch", "localPatch"), ("Custom", "custom")])
        self.sample_count = _number(1, 64, 16, True)
        self.neighbor_count = _number(1, 128, 6, True)
        self.neighbor_radius = _number(0, 1e12, 0)
        self.neighbor_radius.setSpecialValueText("Unlimited")
        self.driver_region_mode = _combo([("Global", "global"), ("Local Patch", "localPatch")])
        self.spacing_region_mode = _combo([("Global", "global"), ("Driver Patch", "driverPatch")])
        self.collision_region_mode = _combo([("Global", "global"), ("Driver Patch", "driverPatch")])
        self.driver_region_rings = _number(0, 128, 12, True)
        self.spacing_region_rings = _number(0, 128, 8, True)
        self.collision_region_rings = _number(0, 128, 8, True)
        self.bind_controls = [self.sample_count, self.neighbor_count, self.neighbor_radius,
                              self.driver_region_mode, self.driver_region_rings,
                              self.spacing_region_mode, self.spacing_region_rings,
                              self.collision_region_mode, self.collision_region_rings]
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)
        form.addRow("Preset", self.preset)
        self.preset_note = _note("")
        form.addRow(self.preset_note)
        advanced = self._foldout(layout, "Advanced binding", "Show sampling and region settings for the next bind. Changing these does not update an existing bind; rebind in the rest pose to apply them.")
        advanced.addWidget(_note("For the next bind only. Changes require rebinding."))
        form = self._group(advanced, "Samples and regions")
        for label, widget in (("Samples per island", self.sample_count),
                              ("Neighbors per island", self.neighbor_count), ("Neighbor radius", self.neighbor_radius),
                              ("Driver region", self.driver_region_mode), ("Driver rings", self.driver_region_rings),
                              ("Spacing region", self.spacing_region_mode), ("Spacing rings", self.spacing_region_rings),
                              ("Collision region", self.collision_region_mode), ("Collision rings", self.collision_region_rings)):
            form.addRow(label, widget)
        self.bind_collision_note = _note("Collision checks the fixed neighbor graph stored at bind time. Excluded pairs will not collide; rebind with more neighbors to add links.")
        form.addRow(self.bind_collision_note)
        advanced.addWidget(_note("Rings count connected driver-face steps: 0 = anchor face, 1 = its edge "
                               "neighbors. Cover the attachment area without reaching the other side of a nearby gap. "
                               "Denser meshes need more rings to cover the same area."))
        self.bind_footer.addWidget(self._button("Bind Meshes", self.bind_selected,
            "Attach the driven mesh's rigid islands to the driver using these settings. Bind in the intended rest pose. Collision starts off; set Collision to 1 in Maya's Attribute Editor to correct additional penetration while preserving bind-pose overlap."))
        layout.addStretch()
        self.preset.activated.connect(lambda *_: self._apply_preset())
        for widget in self.bind_controls:
            signal = widget.currentIndexChanged if isinstance(widget, QtWidgets.QComboBox) else widget.valueChanged
            signal.connect(self._bind_changed)

    def _bind_changed(self, *_):
        if not self._preset_update:
            self.preset.setCurrentIndex(self.preset.findData("custom"))
        self._update_bind_state()

    def _apply_preset(self):
        preset = self.preset.currentData()
        if preset != "custom":
            self._preset_update = True
            try:
                self.sample_count.setValue(16)
                self.neighbor_count.setValue(6)
                self.neighbor_radius.setValue(0)
                self.driver_region_mode.setCurrentIndex(1 if preset == "localPatch" else 0)
                self.spacing_region_mode.setCurrentIndex(1 if preset == "localPatch" else 0)
                self.collision_region_mode.setCurrentIndex(0)
                for widget, value in ((self.driver_region_rings, 12), (self.spacing_region_rings, 8), (self.collision_region_rings, 8)):
                    widget.setValue(value)
            finally:
                self._preset_update = False
        self._update_bind_state()

    def _update_bind_state(self):
        self.driver_region_rings.setEnabled(self.driver_region_mode.currentData() != "global")
        self.spacing_region_rings.setEnabled(self.spacing_region_mode.currentData() != "global")
        self.collision_region_rings.setEnabled(self.collision_region_mode.currentData() != "global")
        self.preset_note.setText({
            "general": "Standard settings for an open surface.",
            "localPatch": "Keeps driver samples and spacing within a local surface region.",
            "custom": "Your settings from Advanced binding."
        }[self.preset.currentData()])

    def _build_tools_tab(self):
        layout = self._page("Tools")
        form = self._group(layout, "Contact report")
        form.addRow(self._button("Check Contacts", self.check_contacts,
            "Measure remaining collision-shape penetration beyond the allowed bind-pose overlap for the active node at the current frame. Reports penetration and solve passes without creating nodes. Run again after changes."))
        self.contact_result = _note("Check penetration beyond bind-pose overlap at the current frame.")
        self.contact_result.setToolTip("Reports collision-shape penetration beyond the allowed bind-pose overlap, before envelope/vertex-weight blending. It does not measure final mesh intersections. Creates no debug nodes.")
        form.addRow(self.contact_result)
        form.addRow(self._button("Expand Collision Neighbors", self.expand_collision_neighbors,
            "Add neighbors of the currently stored collision neighbors. Uses bind data only, so it is safe at any animation frame. Keeps attachment and spacing unchanged. Undo restores the previous graph. More links cost more time and can change collision motion; repeated use widens the graph further."))
        proxy_layout = self._foldout(layout, "Animation proxy", "Show options for creating a reduced mesh that follows the same driver. Hide the high-resolution mesh while animating to reduce viewport work.")
        form = self._group(proxy_layout, "Proxy settings")
        self.proxy_scale = _number(0.01, 100, 1)
        self.proxy_max_vertices = _number(3, 1000000, 16, True)
        self.proxy_name = QtWidgets.QLineEdit()
        self.proxy_name.setPlaceholderText("Automatic name")
        form.addRow("Scale", self.proxy_scale)
        form.addRow("Maximum vertices per island", self.proxy_max_vertices)
        form.addRow("Name", self.proxy_name)
        form.addRow(self._button("Create Proxy", self.create_proxy,
            "Create a reduced mesh and its rigidWrap deformer from the active node. Uses the proxy settings above. Hide the original high-resolution mesh manually when animating with the proxy."))
        debug_layout = self._foldout(layout, "Viewport debug", "Show controls for visualizing collision shapes and spacing links. Drawing options do not change the deformation settings.")
        form = self._group(debug_layout, "Display")
        self.debug_mode = _combo([("Current footprint", "current"), ("Radius", "radius"), ("Capsule", "capsule"),
                                  ("Convex hull", "convexHull"), ("All footprints", "all")])
        form.addRow("Draw", self.debug_mode)
        row = QtWidgets.QHBoxLayout()
        self.show_edges = QtWidgets.QCheckBox("Spacing links")
        self.show_edges.setChecked(True)
        self.xray, self.show_lift = QtWidgets.QCheckBox("X-ray"), QtWidgets.QCheckBox("Lift vectors")
        for widget in (self.show_edges, self.xray, self.show_lift):
            row.addWidget(widget)
        form.addRow(row)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self._button("Draw / Refresh", self.draw_debug,
            "Create or replace the active node's debug locator using these display options. Enable Solve Collision Debug on the locator for collision pairs and correction arrows."))
        row.addWidget(self._button("Clear Debug", self.clear_debug,
            "Remove debug locators connected to the active rigidWrap node. The driven mesh and deformer are kept."))
        form.addRow(row)
        layout.addStretch()

    def _mesh(self, text):
        matches = cmds.ls(text.strip(), long=True, objectsOnly=True) if text.strip() else []
        if len(matches) != 1:
            raise ValueError("Choose one unambiguous mesh for each field.")
        node = matches[0]
        shapes = [node] if cmds.nodeType(node) == "mesh" else cmds.listRelatives(node, shapes=True, noIntermediate=True, fullPath=True, type="mesh") or []
        if len(shapes) != 1 or cmds.getAttr(shapes[0] + ".intermediateObject"):
            raise ValueError("Choose a mesh shape or a transform containing one visible mesh.")
        return shapes[0]

    def capture_mesh(self, field):
        selection = cmds.ls(selection=True, long=True, objectsOnly=True) or []
        if len(selection) != 1:
            raise ValueError("Select one mesh, then click its Use Selected button.")
        field.setText(self._mesh(selection[0]))

    def refresh_nodes(self, preferred=""):
        # UUIDs keep the active choice attached to its node across rename/undo.
        nodes = (cmds.ls(type="rigidWrap") or []) if hasattr(cmds, "rigidWrapBind") else []
        entries = [(node, cmds.ls(node, uuid=True)[0]) for node in sorted(nodes)]
        current = self.active_node.currentData()
        if preferred and cmds.objExists(preferred):
            current = cmds.ls(preferred, uuid=True)[0]
        if entries != self._node_entries or preferred:
            self._node_entries = entries
            blocker = QtCore.QSignalBlocker(self.active_node)
            self.active_node.clear()
            self.active_node.addItem("Choose a node…", "")
            for name, uuid in entries:
                self.active_node.addItem(name, uuid)
            self.active_node.setCurrentIndex(max(0, self.active_node.findData(current)))
            del blocker

    def _current_node(self, required=True):
        uuid = self.active_node.currentData()
        matches = cmds.ls(uuid, long=True) if uuid else []
        node = matches[0] if matches and cmds.nodeType(matches[0]) == "rigidWrap" else ""
        if required and not node:
            raise ValueError("Choose an active rigidWrap node, or select its driven mesh and click Use Selected.")
        return node

    def use_selected_node(self):
        node = selected_rigid_wrap()
        if not node:
            raise ValueError("Select a rigidWrap node or its driven mesh in Maya.")
        self.refresh_nodes(preferred=node)
        self._set_status("Active node: " + node)

    def bind_selected(self):
        plugin_ready()
        driven, driver = self._mesh(self.driven_mesh.text()), self._mesh(self.driver_mesh.text())
        if cmds.ls(driven, uuid=True) == cmds.ls(driver, uuid=True):
            raise ValueError("Driven mesh and driver must be different meshes.")
        if first_rigid_wrap_from_node(driven):
            raise ValueError("The driven mesh already has rigidWrap. Edit it in Maya's Attribute Editor, or remove its existing rigidWrap deformer in Maya before binding again in the rest pose.")
        args = ["-sampleCount", self.sample_count.value(), "-spacingNeighborCount", self.neighbor_count.value(),
                "-spacingNeighborRadius", self.neighbor_radius.value(),
                "-driverRegionMode", self.driver_region_mode.currentData(), "-driverRegionRings", self.driver_region_rings.value(),
                "-spacingRegionMode", self.spacing_region_mode.currentData(), "-spacingRegionRings", self.spacing_region_rings.value(),
                "-collisionRegionMode", self.collision_region_mode.currentData(), "-collisionRegionRings", self.collision_region_rings.value(), driven, driver]
        created = cmds.rigidWrapBind(*args)
        self.refresh_nodes(preferred=created)
        data = cmds.getAttr(created + ".bindData").split()
        count = data[data.index("islandCount") + 1]
        self._set_status("Bound {} islands: {}. Settings are in Maya's Attribute Editor.".format(count, created))
        return created

    def check_contacts(self):
        plugin_ready()
        node = self._current_node()
        self.contact_result.setText("Contact report unavailable until the check succeeds.")
        report = json.loads(cmds.rigidWrapDebugDraw("-report", node))
        prefix = "{} — frame {:g}: ".format(node, cmds.currentTime(query=True))
        message = "collision is off; no active contact solve." if not report["collisionEnabled"] else "{} unresolved contacts; maximum excess penetration {:.6g}; {} solve passes.".format(report["unresolvedContactCount"], report["maxPenetration"], report["collisionIterationsUsed"])
        self.contact_result.setText(prefix + message + " Snapshot only; check again after changes.")
        self._set_status("Contact check completed for " + node)
        return report

    def expand_collision_neighbors(self):
        plugin_ready()
        node = self._current_node()
        result = _expand_collision_neighbors(node, rings=2)
        self.contact_result.setText("Collision links expanded; run Check Contacts for a new snapshot.")
        self._set_status("{}: {} → {} fixed collision links. Undo restores the previous graph.".format(node, result["before"], result["after"]))
        return result

    def create_proxy(self):
        plugin_ready()
        node = self._current_node()
        args = ["-scale", self.proxy_scale.value(), "-maxVertices", self.proxy_max_vertices.value()]
        if self.proxy_name.text().strip():
            args.extend(["-name", self.proxy_name.text().strip()])
        created = cmds.rigidWrapCreateProxy(*(args + [node]))
        if created and cmds.objExists(created):
            cmds.select(created, replace=True)
            self._set_status("Created proxy {}. Active node remains {}.".format(created, node))
        return created

    def draw_debug(self):
        plugin_ready()
        node = self._current_node()
        args = ["-mode", self.debug_mode.currentData()]
        if not self.show_edges.isChecked():
            args.append("-noEdges")
        if self.xray.isChecked():
            args.append("-xray")
        if self.show_lift.isChecked():
            args.append("-lift")
        debug_node = cmds.rigidWrapDebugDraw(*(args + [node]))
        self._set_status("Debug drawing refreshed for " + node)
        return debug_node

    def clear_debug(self):
        plugin_ready()
        node = self._current_node()
        result = cmds.rigidWrapDebugDraw("-clear", node)
        self._set_status("Cleared debug for " + node)
        return result

    def _refresh_scene(self):
        if self.isVisible():
            self._run(self.refresh_nodes)

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


def show():
    global _WINDOW
    # Include windows from a previous importlib.reload of this module.
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if widget.objectName() in ("rigidWrapPySideWindow", "rigidWrapUserGuideWindow"):
            widget.close()
            widget.deleteLater()
    _WINDOW = RigidWrapWindow(parent=_maya_main_window())
    _WINDOW.show()
    _WINDOW.raise_()
    _WINDOW.activateWindow()
    return _WINDOW


open = show
