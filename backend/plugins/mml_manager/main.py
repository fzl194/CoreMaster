# backend/plugins/mml_manager/main.py
from fastapi import APIRouter, UploadFile, File
from core.plugin.context import PluginContext
from core.services.parser import ParserService


class Plugin:
    def __init__(self):
        self.router = APIRouter()
        self.parser: ParserService | None = None

    async def on_register(self, ctx: PluginContext) -> None:
        self.parser = ctx.get_service(ParserService)
        ctx.register_menu("MML 管理", "document", "/plugins/mml-manager")

        @self.router.post("/parse")
        async def parse_mml(file: UploadFile = File(...)):
            content = (await file.read()).decode("utf-8")
            commands = self.parser.parse_text(content)
            return {"commands": commands, "count": len(commands)}

        @self.router.post("/parse-text")
        async def parse_mml_text(payload: dict):
            commands = self.parser.parse_text(payload["text"])
            return {"commands": commands, "count": len(commands)}
