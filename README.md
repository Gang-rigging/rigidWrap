# rigidWrap 1.1.0

rigidWrap is an Autodesk Maya deformer for scales, bark, armor plates, and other
rigid surface details. Each connected mesh island follows a deforming driver
surface while preserving its shape at full deformation strength.

**Windows release: free for individual users, with no activation, license file,
or expiry.**

## Download

[Download rigidWrap 1.1.0 for Maya 2023 and Maya 2024 (Windows x64)](https://github.com/Gang-rigging/rigidWrap/releases/download/v1.1.0/rigidWrap-1.1.0-maya2023-2024-windows-x64.zip)

The combined package contains separate binaries for Maya 2023 and Maya 2024,
one shared Python/MEL scripts folder, and a module file that selects the matching
binary. Use the binary built for your Maya version.

## Features

- Preserve rigid shapes while following a deforming surface.
- Spacing relaxation and tangent blending.
- Procedural collision response, surface sliding, and collision lift.
- GPU-accelerated vertex deformation when Maya and the scene support it.
- Reduced animation proxies and collision/spacing inspection tools.

Collision works between linked rigid islands and preserves intentional bind-pose
overlap. Results are approximate; inspect contact and neighbor coverage in your scene.

## Installation

1. Extract the release ZIP to a stable folder, for example
   `C:/plugins/rigidWrap-1.1.0-maya2023-2024-windows-x64`.
2. In each Maya version's `Maya.env`, add the package root to `MAYA_MODULE_PATH`:

   ```text
   MAYA_MODULE_PATH=C:/plugins/rigidWrap-1.1.0-maya2023-2024-windows-x64
   ```

   Use your actual path. Append to existing module paths using a semicolon.
   `Maya.env` is usually in `Documents/maya/2023` or `Documents/maya/2024`.
3. Keep `rigidWrap.mod`, `plug-ins`, and `scripts` together. Restart Maya.
4. Open **Windows > Settings/Preferences > Plug-in Manager** and load `rigidWrap`.
5. Run this in Maya's **Python** Script Editor:

   ```python
   import rigidWrapUI
   rigidWrapUI.show()
   ```

Maya selects its matching `.mll` and discovers the shared scripts through the
module file. Replace older rigidWrap search paths when switching to this package.
See [README.txt](README.txt) for manual installation instructions.

## Documentation and support

- [User guide](https://www.cgdzg.com/docs/rigidWrap_User_Guide.html)
- [Report an issue](https://github.com/Gang-rigging/rigidWrap/issues/)
- [Main website](https://www.cgdzg.com/)

The UI's **Help > User Guide** and **Help > Report Issue** open these pages in
your default browser. An internet connection is required for the online pages.

When reporting an issue, include your Maya version, Windows version, rigidWrap
version, reproduction steps, and the exact error message. Share a minimal scene
only when you have permission to share its contents.

## Package layout

```text
rigidWrap.mod
README.txt
plug-ins/
  maya2023/rigidWrap.mll
  maya2024/rigidWrap.mll
scripts/
  AErigidWrapTemplate.mel
  AErigidWrapDebugLocatorTemplate.mel
  rigidWrapUI.py
  rigidWrapGpuCheck.py
```

## Validation

This release passed package loading, binding, scene reload, and UI checks in
Maya 2023 and Maya 2024 on Windows. Viewport GPU behavior depends on the graphics
hardware, Maya evaluator configuration, and scene.

Created by Zhenggang Deng.
