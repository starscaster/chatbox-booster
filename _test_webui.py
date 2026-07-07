import sys, os, signal
sys.path.insert(0, r"I:\codex\CBB260701")
os.chdir(r"I:\codex\CBB260701")

from app.core.config import Config, ensure_config_exists
from app.core.shared_services import SharedContext
from app.core.plugin_manager import PluginManager
from app.manager.web_server import run_web_server

ensure_config_exists()
config = Config()
ctx = SharedContext(config)
pm = PluginManager(ctx)
pm.discover()
ctx.logger.info(f"Discovered {len(pm.plugins)} plugin(s)")
ctx.logger.info("Starting web server...")
run_web_server(ctx, pm)