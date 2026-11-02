"""Every third-party plugin in the marketplace must be pinned to a full commit sha."""
import json, pathlib, re, sys

root = pathlib.Path(__file__).resolve().parent.parent
plugins = json.loads((root / ".claude-plugin/marketplace.json").read_text())["plugins"]
bad = [p["name"] for p in plugins
       if not isinstance(p["source"], str) and not re.fullmatch(r"[0-9a-f]{40}", p["source"].get("sha", ""))]
local = [p["name"] for p in plugins if isinstance(p["source"], str) and not p["source"].startswith("./")]
if bad or local:
    sys.exit(f"unpinned external plugins: {bad + local}")
print(f"marketplace: {len(plugins)} plugins, externals pinned")
