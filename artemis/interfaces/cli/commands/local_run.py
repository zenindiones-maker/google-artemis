"""Executor local restrito: Ollama + abertura autorizada de URL no Firefox."""
import os

import typer
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from artemis.tools.mobile.open_url_firefox import launch_url_in_firefox


OPEN_URL_TOOL = {
    "name": "open_url_firefox",
    "description": (
        "Solicita abertura de uma URL HTTP(S) no Firefox Android. "
        "A ferramenta exige aprovação explícita do usuário."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL HTTP(S) absoluta"}
        },
        "required": ["url"],
        "additionalProperties": False,
    },
}


def dispatch_tool_calls(tool_calls, launcher=None):
    if not tool_calls:
        return None
    if len(tool_calls) != 1:
        raise RuntimeError("Somente uma chamada de ferramenta por execução é permitida.")

    call = tool_calls[0]
    if call.get("name") != "open_url_firefox":
        raise RuntimeError("Ferramenta não permitida neste executor local.")

    args = call.get("args")
    if not isinstance(args, dict) or set(args) != {"url"}:
        raise ValueError("Argumentos inválidos para open_url_firefox.")
    url = args["url"]
    if not isinstance(url, str) or not url:
        raise ValueError("A URL precisa ser uma string não vazia.")

    if launcher is None:
        launcher = launch_url_in_firefox
    return launcher(url)


def local_run_command(goal: str) -> None:
    """Executa uma tarefa local restrita, sem inicializar agente ADB."""
    if os.environ.get("ARTEMIS_LOCAL_ONLY") != "1":
        typer.echo("Defina ARTEMIS_LOCAL_ONLY=1 para autorizar o modo local.", err=True)
        raise typer.Exit(code=2)

    model_name = os.environ.get(
        "ARTEMIS_LOCAL_MODEL", "artemis-qwen-local:latest"
    )
    model = ChatOpenAI(
        model=model_name,
        base_url="http://127.0.0.1:11434/v1",
        api_key="ollama-local",
        temperature=0,
    )

    try:
        response = model.bind_tools([OPEN_URL_TOOL]).invoke([
            SystemMessage(content=(
                "Você é o Artemis local. A única ferramenta disponível é "
                "open_url_firefox. Use-a para pedidos de abertura de URL. "
                "Nunca alegue que uma ação ocorreu sem executar a ferramenta. "
                "Não invente URLs."
            )),
            HumanMessage(content=goal),
        ])
        if not response.tool_calls:
            typer.echo(str(response.content or "O modelo não solicitou nenhuma ação."))
            return

        result = dispatch_tool_calls(response.tool_calls)
        typer.echo(str(result))
    except Exception as exc:
        typer.echo(f"Falha no executor local: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
