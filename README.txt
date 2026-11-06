rigidWrap 1.1.0 - Maya 2023 and Maya 2024 / Windows x64

Free for individual users. No activation, license file, or expiry.

One package, shared scripts, separate binaries:
  rigidWrap.mod
  plug-ins/maya2023/rigidWrap.mll
  plug-ins/maya2024/rigidWrap.mll
  scripts/  (shared Python and MEL files for both Maya versions)

Installation:
1. Extract this folder to a stable location, for example:
   C:/plugins/rigidWrap-1.1.0-maya2023-2024-windows-x64
2. In each Maya version's Maya.env, add the package root to MAYA_MODULE_PATH:
   MAYA_MODULE_PATH=C:/plugins/rigidWrap-1.1.0-maya2023-2024-windows-x64
   Use your actual path. Append to existing paths using a semicolon.
   Maya.env is usually in Documents/maya/2023 or Documents/maya/2024.
3. Restart Maya. Its module system selects the correct binary and discovers
   the shared scripts. Keep rigidWrap.mod in the package root.
4. Load rigidWrap in Maya's Plug-in Manager, then run in the Python tab:
   import rigidWrapUI; rigidWrapUI.show()

Manual installation without the module file:
Add only plug-ins/maya2023 OR plug-ins/maya2024 to MAYA_PLUG_IN_PATH for
the matching Maya version. Add the shared scripts folder to MAYA_SCRIPT_PATH
and PYTHONPATH. Do not add both binary folders to the same Maya session.
Replace any older rigidWrap search paths when switching to this package.

Help > User Guide opens:
https://www.cgdzg.com/docs/rigidWrap_User_Guide.html
Help > Report Issue opens:
https://github.com/Gang-rigging/rigidWrap/issues/
Both links open in your default browser and require an internet connection.
